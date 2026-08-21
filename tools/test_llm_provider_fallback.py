"""Regression test for Gate 12d/12e: llm.client's provider fallback and
Groq rate-limit header logging.

Confirms three things with a fully mocked provider dispatch - no real
network calls, no API quota spent:

1. When the primary provider fails, generate() (the buffered call path
   agent.drafter.understand_request() and agent.qa.answer_question() both
   use) retries the fallback and returns its COMPLETE result rather than
   giving up or returning a partial - the property that makes buffered
   calls safe to restart where llm.client.generate_stream() genuinely isn't
   (see that function's docstring).
2. Every failure along the way is logged - the silent version of this is
   exactly how CHECK B's classification failing under provider load
   produced a normal-looking "ok" response with "Unknown - could not
   determine automatically" as the authority and nothing in any log to
   explain why (Gate 12's diagnosis).
3. _log_groq_rate_limit() (Gate 12e) degrades to a no-op on malformed or
   missing headers instead of ever breaking the actual generate() call.

Usage:
    python -m tools.test_llm_provider_fallback
"""
import io
import os
import sys

import llm.client as llm_client
from llm.client import LLMError


def test_fallback_succeeds_after_primary_failure():
    calls = []
    fallback = "groq" if llm_client.PROVIDER == "gemini" else "gemini"

    def fake_dispatch(provider, prompt, system, tools, max_tokens):
        calls.append(provider)
        if provider == llm_client.PROVIDER:
            raise LLMError("simulated failure on the primary provider")
        return "COMPLETE FALLBACK RESPONSE"

    original_dispatch = llm_client._dispatch
    original_stderr = sys.stderr
    llm_client._dispatch = fake_dispatch
    sys.stderr = io.StringIO()
    try:
        result = llm_client.generate("test prompt")
        log_output = sys.stderr.getvalue()
    finally:
        llm_client._dispatch = original_dispatch
        sys.stderr = original_stderr

    assert result == "COMPLETE FALLBACK RESPONSE", (
        f"expected the fallback's complete response, got: {result!r}"
    )
    assert calls == [llm_client.PROVIDER, fallback], (
        f"expected primary-then-fallback call order, got: {calls}"
    )
    assert "failed" in log_output and "retrying on" in log_output, (
        f"expected a failure log line, got: {log_output!r}"
    )
    print("PASS: fallback returns a complete result after a primary-provider failure, and it's logged")


def test_both_providers_failing_is_logged_and_fails_open_correctly():
    import agent.drafter as drafter

    def fake_dispatch(provider, prompt, system, tools, max_tokens):
        raise LLMError(f"simulated total outage ({provider})")

    original_dispatch = llm_client._dispatch
    original_stderr = sys.stderr
    llm_client._dispatch = fake_dispatch
    sys.stderr = io.StringIO()
    try:
        result = drafter.understand_request("write me a poem about cricket")
        log_output = sys.stderr.getvalue()
    finally:
        llm_client._dispatch = original_dispatch
        sys.stderr = original_stderr

    assert result.in_scope is None, f"expected in_scope=None on total provider failure, got {result.in_scope}"
    assert result[0] == [], f"expected empty information_sought, got {result[0]}"
    assert "scope check unavailable" in log_output, (
        f"expected the new explicit classification-unavailable log line, got: {log_output!r}"
    )
    print("PASS: a total provider failure during CHECK B is now logged, and still fails open correctly")


def test_groq_rate_limit_logging_cannot_break_on_malformed_headers():
    """Gate 12e: _log_groq_rate_limit() must degrade to a no-op if the header
    shape ever changes - it must never be the reason a real generate() call
    fails. Exercises the actual function, not a re-implementation of it,
    against a normal dict, a headers object missing the expected keys, and
    an object that raises on .get() entirely.
    """

    class ExplodingHeaders:
        def get(self, key):
            raise RuntimeError("simulated header-shape change")

    original_stderr = sys.stderr

    # Normal case: both headers present - should log one line, not raise.
    sys.stderr = io.StringIO()
    try:
        llm_client._log_groq_rate_limit({"x-ratelimit-remaining-requests": "29", "x-ratelimit-remaining-tokens": "7500"})
        log_output = sys.stderr.getvalue()
    finally:
        sys.stderr = original_stderr
    assert "29" in log_output and "7500" in log_output, f"expected both values logged, got: {log_output!r}"

    # Missing keys entirely - must not raise, and must not print (nothing to report).
    sys.stderr = io.StringIO()
    try:
        llm_client._log_groq_rate_limit({})
        log_output = sys.stderr.getvalue()
    finally:
        sys.stderr = original_stderr
    assert log_output == "", f"expected no output when no rate-limit headers are present, got: {log_output!r}"

    # Headers object that raises on access entirely - must not propagate.
    sys.stderr = io.StringIO()
    try:
        llm_client._log_groq_rate_limit(ExplodingHeaders())
    except Exception as e:
        raise AssertionError(f"_log_groq_rate_limit must never raise, but it raised: {e!r}")
    finally:
        sys.stderr = original_stderr

    print("PASS: Groq rate-limit header logging degrades to a no-op instead of breaking the call path")


def test_raw_response_path_rate_limit_still_triggers_fallback():
    """Gate 12e: GROQ_LOG_RATE_LIMITS's with_raw_response.create() call path
    is untested against the real API (that's the whole reason it's gated
    behind an opt-in flag rather than always on). This proves the one thing
    that matters most if it's ever turned on: a RateLimitError raised from
    THAT specific call site is still caught as groq_sdk.RateLimitError (not
    some different exception type with_raw_response wraps it in) and still
    lets generate()'s provider fallback succeed - exercised end-to-end
    through the real _generate_groq()/_generate_gemini(), with only the SDK
    client classes mocked, not llm.client's own dispatch logic.
    """
    import httpx
    import groq as groq_sdk

    fake_request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    fake_response = httpx.Response(status_code=429, request=fake_request)
    rate_limit_error = groq_sdk.RateLimitError("simulated rate limit", response=fake_response, body=None)

    class FakeWithRawResponse:
        def create(self, **kwargs):
            raise rate_limit_error

    class FakeGroqCompletions:
        with_raw_response = FakeWithRawResponse()

        def create(self, **kwargs):
            raise AssertionError("plain .create() should not be called when GROQ_LOG_RATE_LIMITS is on")

    class FakeGroqChat:
        completions = FakeGroqCompletions()

    class FakeGroqClient:
        def __init__(self, api_key):
            self.chat = FakeGroqChat()

    class FakeGeminiMessage:
        text = "COMPLETE GEMINI FALLBACK RESPONSE"

    class FakeGeminiModels:
        def generate_content(self, model, contents, config):
            class FakeResponse:
                text = "COMPLETE GEMINI FALLBACK RESPONSE"
                candidates = []
            return FakeResponse()

    class FakeGeminiClient:
        def __init__(self, api_key):
            self.models = FakeGeminiModels()

    original_groq_class = groq_sdk.Groq
    original_flag = llm_client.GROQ_LOG_RATE_LIMITS
    original_stderr = sys.stderr
    original_groq_key = os.environ.get("GROQ_API_KEY")
    original_gemini_key = os.environ.get("GEMINI_API_KEY")

    import google.genai as genai
    original_genai_client = genai.Client

    groq_sdk.Groq = FakeGroqClient
    genai.Client = FakeGeminiClient
    llm_client.GROQ_LOG_RATE_LIMITS = True
    os.environ["GROQ_API_KEY"] = "fake-key-for-test"
    os.environ["GEMINI_API_KEY"] = "fake-key-for-test"
    sys.stderr = io.StringIO()
    try:
        result = llm_client.generate("test prompt")
        log_output = sys.stderr.getvalue()
    finally:
        groq_sdk.Groq = original_groq_class
        genai.Client = original_genai_client
        llm_client.GROQ_LOG_RATE_LIMITS = original_flag
        sys.stderr = original_stderr
        if original_groq_key is None:
            os.environ.pop("GROQ_API_KEY", None)
        else:
            os.environ["GROQ_API_KEY"] = original_groq_key
        if original_gemini_key is None:
            os.environ.pop("GEMINI_API_KEY", None)
        else:
            os.environ["GEMINI_API_KEY"] = original_gemini_key

    assert result == "COMPLETE GEMINI FALLBACK RESPONSE", (
        f"expected the Gemini fallback's complete response, got: {result!r}"
    )
    assert "failed" in log_output and "retrying on" in log_output, (
        f"expected the primary-failure log line, got: {log_output!r}"
    )
    print("PASS: a RateLimitError from the with_raw_response call path still triggers provider fallback correctly")


if __name__ == "__main__":
    test_fallback_succeeds_after_primary_failure()
    test_both_providers_failing_is_logged_and_fails_open_correctly()
    test_groq_rate_limit_logging_cannot_break_on_malformed_headers()
    test_raw_response_path_rate_limit_still_triggers_fallback()
    print("\nAll Gate 12d/12e fallback and logging tests passed. No real API calls were made.")
