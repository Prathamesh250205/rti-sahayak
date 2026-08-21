"""Regression test for Gate 12d: llm.client.generate()'s provider fallback.

Confirms two things with a fully mocked provider dispatch - no real network
calls, no API quota spent:

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

Usage:
    python -m tools.test_llm_provider_fallback
"""
import io
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


if __name__ == "__main__":
    test_fallback_succeeds_after_primary_failure()
    test_both_providers_failing_is_logged_and_fails_open_correctly()
    print("\nAll Gate 12d fallback tests passed. No real API calls were made.")
