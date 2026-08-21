"""Regression test for Gate 12d/12e/13: llm.client's provider fallback,
Groq rate-limit header logging, and the 3-provider chain (Groq -> Gemini ->
Anthropic).

Confirms all of the following with a fully mocked provider dispatch - no
real network calls, no API quota spent:

1. When a provider fails, generate() (the buffered call path
   agent.drafter.understand_request() and agent.qa.answer_question() both
   use) retries the next provider in the chain and returns its COMPLETE
   result rather than giving up or returning a partial - the property that
   makes buffered calls safe to restart where llm.client.generate_stream()
   genuinely isn't (see that function's docstring).
2. Every failure along the way is logged - the silent version of this is
   exactly how CHECK B's classification failing under provider load
   produced a normal-looking "ok" response with "Unknown - could not
   determine automatically" as the authority and nothing in any log to
   explain why (Gate 12's diagnosis).
3. _log_groq_rate_limit() (Gate 12e) degrades to a no-op on malformed or
   missing headers instead of ever breaking the actual generate() call.
4. The provider chain order is genuinely configurable via env
   (LLM_PROVIDER_CHAIN / LLM_PROVIDER), and a 3-provider chain actually
   reaches its third hop - Groq failing and Gemini also failing lands on
   Anthropic, not a give-up after 2 hops (Gate 13).

Usage:
    python -m tools.test_llm_provider_fallback
"""
import io
import os
import sys

import llm.client as llm_client
from llm.client import LLMError


def test_fallback_succeeds_after_primary_failure():
    """Gate 13 lesson: this test used to derive its expected fallback as
    "groq" if llm_client.PROVIDER == "gemini" else "gemini" - a leftover
    2-provider assumption that silently broke the moment LLM_PROVIDER_CHAIN
    was set to anthropic-first in .env (PROVIDER became "anthropic", the
    hardcoded either/or no longer covered the real chain, and the test
    crashed the whole verification script before it ever reached the paid
    endpoints). Fixed by setting an explicit, deterministic PROVIDER_CHAIN
    for this test's own scope instead of reading whatever chain the
    environment happens to be configured with - the test's job is to prove
    generic chain behavior, not to assume any particular .env config.
    """
    calls = []
    original_chain = llm_client.PROVIDER_CHAIN
    llm_client.PROVIDER_CHAIN = ("primary_test_provider", "fallback_test_provider")

    def fake_dispatch(provider, prompt, system, tools, max_tokens):
        calls.append(provider)
        if provider == llm_client.PROVIDER_CHAIN[0]:
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
        llm_client.PROVIDER_CHAIN = original_chain
        sys.stderr = original_stderr

    assert result == "COMPLETE FALLBACK RESPONSE", (
        f"expected the fallback's complete response, got: {result!r}"
    )
    assert calls == ["primary_test_provider", "fallback_test_provider"], (
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

    Explicitly forces PROVIDER_CHAIN to (groq, gemini) for its own scope -
    without this, whatever chain the environment happens to be configured
    with applies, and only Groq/Gemini are mocked here. With Anthropic
    promoted to chain[0] (Gate 13's anthropic-first config), an unmocked
    Anthropic would be tried FIRST and this "mocked, zero-cost" test would
    silently make a real, billed call to the live API before ever reaching
    the Groq/Gemini mocks below - exactly the class of bug this comment
    exists to prevent from recurring (see
    test_fallback_succeeds_after_primary_failure's docstring for the first
    occurrence).
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
        def __init__(self, **kwargs):
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
    original_chain = llm_client.PROVIDER_CHAIN
    original_stderr = sys.stderr
    original_groq_key = os.environ.get("GROQ_API_KEY")
    original_gemini_key = os.environ.get("GEMINI_API_KEY")

    import google.genai as genai
    original_genai_client = genai.Client

    groq_sdk.Groq = FakeGroqClient
    genai.Client = FakeGeminiClient
    llm_client.GROQ_LOG_RATE_LIMITS = True
    llm_client.PROVIDER_CHAIN = ("groq", "gemini")
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
        llm_client.PROVIDER_CHAIN = original_chain
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


def test_groq_max_retries_is_passed_to_client():
    """Gate 12e: GROQ_MAX_RETRIES must actually reach the Groq() client
    constructor - a config value that exists but is never wired through
    would silently leave the SDK on its own default (2) regardless of what
    this is set to. Mocks groq.Groq itself to capture its constructor
    kwargs directly; exercises the real _generate_groq()/_stream_groq(),
    not a re-implementation of the wiring. No network call - the fake
    client's .chat is never a real completions resource, so the call
    fails immediately after construction, which is fine: the constructor
    call is what this test needs, not a response.
    """
    import groq as groq_sdk

    class FakeChatCompletionsStub:
        def __getattr__(self, name):
            raise RuntimeError("test stub - no real call should be made")

    class FakeGroqClient:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)
            self.chat = FakeChatCompletionsStub()

    original_groq_class = groq_sdk.Groq
    original_env_key = os.environ.get("GROQ_API_KEY")
    original_max_retries = llm_client.GROQ_MAX_RETRIES

    for forced_value in (0, 1, 3):
        captured_kwargs = {}
        groq_sdk.Groq = FakeGroqClient
        os.environ["GROQ_API_KEY"] = "fake-key-for-test"
        llm_client.GROQ_MAX_RETRIES = forced_value
        try:
            try:
                llm_client._generate_groq("test prompt", None, None, None)
            except Exception:
                pass  # expected - the stub chat resource has no real completions
        finally:
            groq_sdk.Groq = original_groq_class
            llm_client.GROQ_MAX_RETRIES = original_max_retries
            if original_env_key is None:
                os.environ.pop("GROQ_API_KEY", None)
            else:
                os.environ["GROQ_API_KEY"] = original_env_key

        assert captured_kwargs.get("max_retries") == forced_value, (
            f"expected max_retries={forced_value} passed to Groq(), got kwargs: {captured_kwargs!r}"
        )

    print("PASS: GROQ_MAX_RETRIES is actually passed to the Groq() client constructor")


def test_provider_chain_order_is_configurable():
    """Gate 13: the chain order must be genuinely configurable via env, not
    hardcoded - LLM_PROVIDER_CHAIN fully overrides the order, and
    LLM_PROVIDER alone (the pre-Gate-13 config) still produces a working
    3-provider chain with the other two filled in behind it. Exercises the
    real _parse_provider_chain(), not a re-implementation of its logic.
    """

    def _set(chain_val, provider_val):
        if chain_val is None:
            os.environ.pop("LLM_PROVIDER_CHAIN", None)
        else:
            os.environ["LLM_PROVIDER_CHAIN"] = chain_val
        if provider_val is None:
            os.environ.pop("LLM_PROVIDER", None)
        else:
            os.environ["LLM_PROVIDER"] = provider_val

    original_chain_env = os.environ.get("LLM_PROVIDER_CHAIN")
    original_provider_env = os.environ.get("LLM_PROVIDER")
    try:
        # Full explicit override wins outright.
        _set("anthropic,groq,gemini", "groq")
        assert llm_client._parse_provider_chain() == ("anthropic", "groq", "gemini"), (
            f"got: {llm_client._parse_provider_chain()!r}"
        )

        # LLM_PROVIDER alone still produces a full 3-provider chain, with
        # the other two filled in behind it in default order.
        _set(None, "anthropic")
        assert llm_client._parse_provider_chain() == ("anthropic", "groq", "gemini")

        _set(None, "gemini")
        assert llm_client._parse_provider_chain() == ("gemini", "groq", "anthropic")

        # Neither set - falls back to the documented default.
        _set(None, None)
        assert llm_client._parse_provider_chain() == ("groq", "gemini", "anthropic")

        # An unknown provider name is a clear, immediate error, not a
        # silent skip - a typo in .env should never quietly narrow the
        # chain to fewer providers than intended.
        _set("groq,not-a-real-provider,anthropic", None)
        try:
            llm_client._parse_provider_chain()
            raise AssertionError("expected LLMError for an unknown provider name")
        except LLMError as e:
            assert "not-a-real-provider" in str(e), f"expected the bad name in the error, got: {e}"
    finally:
        _set(original_chain_env, original_provider_env)

    print("PASS: the provider chain order is genuinely configurable via LLM_PROVIDER_CHAIN/LLM_PROVIDER")


def test_three_hop_chain_groq_then_gemini_then_anthropic():
    """Gate 13: with a full 3-provider chain, Groq failing and Gemini also
    failing must land on Anthropic as the last resort, not give up after 2
    hops (the old code had no concept of a third hop at all). Mocks each
    provider's real SDK client class - no network calls - forces the chain
    order, and checks both the final result and that all three were tried
    in the right order.
    """
    import groq as groq_sdk
    import google.genai as genai
    from google.genai import errors as genai_errors
    import httpx
    import anthropic as anthropic_sdk

    call_order = []

    class FakeGroqCompletions:
        def create(self, **kwargs):
            call_order.append("groq")
            raise groq_sdk.APIConnectionError(request=httpx.Request("POST", "https://api.groq.com/x"))

    class FakeGroqChat:
        completions = FakeGroqCompletions()

    class FakeGroqClient:
        def __init__(self, **kwargs):
            self.chat = FakeGroqChat()

    class FakeGeminiModels:
        def generate_content(self, model, contents, config):
            call_order.append("gemini")
            raise genai_errors.APIError(500, {"error": {"message": "simulated Gemini failure"}})

    class FakeGeminiClient:
        def __init__(self, **kwargs):
            self.models = FakeGeminiModels()

    class FakeTextBlock:
        type = "text"
        text = "COMPLETE ANTHROPIC RESPONSE"

    class FakeAnthropicResponse:
        content = [FakeTextBlock()]

    class FakeAnthropicMessages:
        def create(self, **kwargs):
            call_order.append("anthropic")
            return FakeAnthropicResponse()

    class FakeAnthropicClient:
        def __init__(self, **kwargs):
            self.messages = FakeAnthropicMessages()

    original_groq_class = groq_sdk.Groq
    original_genai_class = genai.Client
    original_anthropic_class = anthropic_sdk.Anthropic
    original_chain = llm_client.PROVIDER_CHAIN
    original_stderr = sys.stderr
    original_keys = {k: os.environ.get(k) for k in ("GROQ_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY")}

    groq_sdk.Groq = FakeGroqClient
    genai.Client = FakeGeminiClient
    anthropic_sdk.Anthropic = FakeAnthropicClient
    llm_client.PROVIDER_CHAIN = ("groq", "gemini", "anthropic")
    for k in original_keys:
        os.environ[k] = "fake-key-for-test"
    sys.stderr = io.StringIO()
    try:
        result = llm_client.generate("test prompt")
        log_output = sys.stderr.getvalue()
    finally:
        groq_sdk.Groq = original_groq_class
        genai.Client = original_genai_class
        anthropic_sdk.Anthropic = original_anthropic_class
        llm_client.PROVIDER_CHAIN = original_chain
        sys.stderr = original_stderr
        for k, v in original_keys.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    assert result == "COMPLETE ANTHROPIC RESPONSE", f"expected Anthropic's response, got: {result!r}"
    assert call_order == ["groq", "gemini", "anthropic"], f"expected chain order groq->gemini->anthropic, got: {call_order}"
    assert llm_client.LAST_PROVIDER_USED == "anthropic", (
        f"expected LAST_PROVIDER_USED='anthropic', got: {llm_client.LAST_PROVIDER_USED!r}"
    )
    assert log_output.count("failed") >= 2, f"expected two failure log lines (groq, gemini), got: {log_output!r}"
    print("PASS: Groq fails -> Gemini fails -> Anthropic succeeds, chain order respected end-to-end")


if __name__ == "__main__":
    test_fallback_succeeds_after_primary_failure()
    test_both_providers_failing_is_logged_and_fails_open_correctly()
    test_groq_rate_limit_logging_cannot_break_on_malformed_headers()
    test_raw_response_path_rate_limit_still_triggers_fallback()
    test_groq_max_retries_is_passed_to_client()
    test_provider_chain_order_is_configurable()
    test_three_hop_chain_groq_then_gemini_then_anthropic()
    print("\nAll Gate 12d/12e/13 fallback and logging tests passed. No real API calls were made.")
