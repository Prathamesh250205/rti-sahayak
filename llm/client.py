"""Thin wrapper around the LLM provider.

Every LLM call in this app goes through generate() (or generate_stream()) so
we can swap providers without touching any other code in the codebase.
Providers are tried in order along PROVIDER_CHAIN; if one fails, the next is
tried automatically, so a single provider's outage or throttle never has to
become a hard failure on its own.
"""
import json
import os
import re
import sys
from typing import Iterator

from dotenv import load_dotenv

load_dotenv()

_KNOWN_PROVIDERS = ("groq", "gemini", "anthropic")


def _parse_provider_chain() -> tuple[str, ...]:
    """LLM_PROVIDER_CHAIN (comma-separated, e.g. "anthropic,groq,gemini")
    fully overrides the fallback order when set. Otherwise LLM_PROVIDER (the
    pre-Gate-13 single-primary config) becomes chain[0], with the other two
    providers filling in behind it in their default order - existing
    LLM_PROVIDER=groq configs keep working unchanged, now extended with
    Anthropic appended as a last resort rather than needing a second env
    var to get any fallback chain at all.
    """
    raw = os.getenv("LLM_PROVIDER_CHAIN", "").strip()
    if raw:
        chain = tuple(p.strip().lower() for p in raw.split(",") if p.strip())
    else:
        primary = os.getenv("LLM_PROVIDER", "groq").strip().lower()
        chain = (primary,) + tuple(p for p in _KNOWN_PROVIDERS if p != primary)

    for p in chain:
        if p not in _KNOWN_PROVIDERS:
            raise LLMError(
                f"Unknown provider '{p}' in LLM_PROVIDER_CHAIN/LLM_PROVIDER. "
                f"Use a comma-separated list of: {', '.join(_KNOWN_PROVIDERS)}."
            )
    if not chain:
        raise LLMError("LLM_PROVIDER_CHAIN resolved to an empty provider chain.")
    return chain


class LLMError(RuntimeError):
    """Raised when the LLM provider call fails. Message is safe to show in the UI."""


PROVIDER_CHAIN = _parse_provider_chain()
PROVIDER = PROVIDER_CHAIN[0]  # backward-compat alias - "the primary provider"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
# claude-haiku-4-5-20251001, not the undated "claude-haiku-4-5" - Haiku 4.5
# is dated where the newer Claude 5-generation model IDs are not (Anthropic
# dropped date suffixes starting with that generation, not before it).
# Classification/Q&A calls here are small and structured; Haiku is fast,
# cheap, and more than sufficient - see the module docstring for why the
# JSON-object prompting this app uses needs no adjustment for Anthropic.
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

# Gate 12e: off by default. Logging Groq's rate-limit headers means calling
# client.chat.completions.with_raw_response.create() instead of the plain
# .create() this project has used (and relied on) all along - a code path
# that hasn't been exercised against the real API, since doing so wasn't
# possible without spending quota already tight enough to be the reason
# this exists. Diagnostic convenience must not be able to change how the
# primary provider path behaves during judging, so the untested path only
# runs when explicitly opted into - flip this on when there's quota to
# smoke-test it, not during a demo.
GROQ_LOG_RATE_LIMITS = os.getenv("GROQ_LOG_RATE_LIMITS", "").strip().lower() in ("1", "true", "yes")

# Gate 12e: the Groq SDK defaults to 2 internal retries, undocumented in
# this codebase until traced through the installed package's source - and
# it retries on HTTP 429 specifically (_should_retry() returns True for
# rate limits, not just 5xx/connection errors). On a 30 RPM ceiling, one
# logical call that fails can silently cost up to 3 real requests in a
# tight backoff burst our own 6s-between-calls pacing has no visibility
# into, since it only spaces out logical calls, not an SDK's retries
# within one. One retry after backoff is still worth it; a second mostly
# spends budget on a request that's already losing. Explicit and
# configurable rather than left at the SDK's default, so demo-day request
# cost per user action is predictable (1 + this many, not 1 + 2).
GROQ_MAX_RETRIES = int(os.getenv("GROQ_MAX_RETRIES", "1"))

# Same reasoning as GROQ_MAX_RETRIES - explicit rather than left at the
# Anthropic SDK's own default (2), for predictable per-call request cost.
ANTHROPIC_MAX_RETRIES = int(os.getenv("ANTHROPIC_MAX_RETRIES", "1"))

# Set after each successful generate() call to whichever provider actually
# served it (PROVIDER or its fallback) — lets the UI show a "served by" badge.
LAST_PROVIDER_USED: str | None = None


def generate(
    prompt: str,
    system: str | None = None,
    tools: list[dict] | None = None,
    max_tokens: int | None = None,
):
    """Generate a response from the first working provider in PROVIDER_CHAIN.

    prompt: the user message.
    system: optional system prompt.
    tools: optional list of {"name", "description", "input_schema"} tool defs.
    max_tokens: optional output cap — set this low for short, simple replies
        to reduce latency; omit for normal-length responses.

    Returns a plain str when tools is None (the common case). When tools is
    given, returns {"text": str, "tool_calls": [{"name", "input"}, ...]} so
    callers can branch on whether the model asked to call a tool.

    Tries each provider in PROVIDER_CHAIN in order, moving to the next on
    any failure. Raises LLMError only if every provider in the chain fails —
    callers should catch this and surface it in the UI rather than crash
    the app.
    """
    global LAST_PROVIDER_USED

    errors = []
    for i, provider in enumerate(PROVIDER_CHAIN):
        try:
            result = _dispatch(provider, prompt, system, tools, max_tokens)
            LAST_PROVIDER_USED = provider
            return result
        except LLMError as e:
            errors.append(f"{provider}: {e}")
            if i + 1 < len(PROVIDER_CHAIN):
                print(f"[llm] {provider} failed ({e}); retrying on {PROVIDER_CHAIN[i + 1]}...", file=sys.stderr)

    raise LLMError(f"All LLM providers failed. {' | '.join(errors)}")


def generate_stream(
    prompt: str, system: str | None = None, max_tokens: int | None = None
) -> Iterator[str]:
    """Like generate(), but yields text chunks as they arrive instead of
    blocking for the full response. No tool-calling support (streaming +
    tool calls need response-shape handling this app doesn't use).

    Tries each provider in PROVIDER_CHAIN in order. Moves to the next
    provider only if the current one fails before yielding any content —
    once a stream has started delivering text, a mid-stream failure
    surfaces as LLMError rather than silently restarting on the next
    provider with a half-shown answer.
    """
    global LAST_PROVIDER_USED

    errors = []
    for i, provider in enumerate(PROVIDER_CHAIN):
        try:
            yielded_any = False
            for chunk in _dispatch_stream(provider, prompt, system, max_tokens):
                yielded_any = True
                yield chunk
            LAST_PROVIDER_USED = provider
            return
        except LLMError as e:
            if yielded_any:
                raise
            errors.append(f"{provider}: {e}")
            if i + 1 < len(PROVIDER_CHAIN):
                print(f"[llm] {provider} failed ({e}); retrying on {PROVIDER_CHAIN[i + 1]}...", file=sys.stderr)

    raise LLMError(f"All LLM providers failed. {' | '.join(errors)}")


def _dispatch(provider: str, prompt: str, system: str | None, tools: list[dict] | None, max_tokens: int | None):
    if provider == "gemini":
        return _generate_gemini(prompt, system, tools, max_tokens)
    if provider == "anthropic":
        return _generate_anthropic(prompt, system, tools, max_tokens)
    return _generate_groq(prompt, system, tools, max_tokens)


def _dispatch_stream(provider: str, prompt: str, system: str | None, max_tokens: int | None) -> Iterator[str]:
    if provider == "gemini":
        return _stream_gemini(prompt, system, max_tokens)
    if provider == "anthropic":
        return _stream_anthropic(prompt, system, max_tokens)
    return _stream_groq(prompt, system, max_tokens)


def _gemini_config_kwargs(system, tools, max_tokens):
    from google.genai import types

    config_kwargs = {}
    if system is not None:
        config_kwargs["system_instruction"] = system
    if max_tokens is not None:
        config_kwargs["max_output_tokens"] = max_tokens
    if tools:
        config_kwargs["tools"] = [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name=t["name"],
                        description=t.get("description", ""),
                        parameters=t.get("input_schema"),
                    )
                    for t in tools
                ]
            )
        ]
    return types.GenerateContentConfig(**config_kwargs) if config_kwargs else None


def _generate_gemini(prompt: str, system: str | None, tools: list[dict] | None, max_tokens: int | None):
    from google import genai
    from google.genai import errors as genai_errors

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise LLMError("GEMINI_API_KEY is not set. Copy .env.example to .env and add your key.")

    client = genai.Client(api_key=api_key)
    config = _gemini_config_kwargs(system, tools, max_tokens)

    try:
        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt, config=config)
    except genai_errors.APIError as e:
        raise LLMError(f"Gemini provider error: {e}")

    return _format_result(
        text=response.text or "",
        tool_calls=_extract_gemini_tool_calls(response),
        tools_requested=tools is not None,
    )


def _stream_gemini(prompt: str, system: str | None, max_tokens: int | None) -> Iterator[str]:
    from google import genai
    from google.genai import errors as genai_errors

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise LLMError("GEMINI_API_KEY is not set. Copy .env.example to .env and add your key.")

    client = genai.Client(api_key=api_key)
    config = _gemini_config_kwargs(system, None, max_tokens)

    try:
        for chunk in client.models.generate_content_stream(model=GEMINI_MODEL, contents=prompt, config=config):
            if chunk.text:
                yield chunk.text
    except genai_errors.APIError as e:
        raise LLMError(f"Gemini provider error: {e}")


def _extract_gemini_tool_calls(response) -> list[dict]:
    calls = []
    for candidate in response.candidates or []:
        for part in candidate.content.parts or []:
            fc = getattr(part, "function_call", None)
            if fc is not None:
                calls.append({"name": fc.name, "input": dict(fc.args or {})})
    return calls


def _groq_messages(system, prompt):
    messages = []
    if system is not None:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return messages


def _log_groq_rate_limit(headers) -> None:
    """Best-effort log of Groq's rate-limit headers on a successful call
    (Gate 12e) - a local trail of remaining budget instead of only finding
    out via a 429. Deliberately isolated from the actual call: if the
    header names or shape ever change, this must degrade to a no-op, never
    to a broken generate()/generate_stream() call. Single line, only when
    at least one of the two headers is actually present.
    """
    try:
        remaining_requests = headers.get("x-ratelimit-remaining-requests")
        remaining_tokens = headers.get("x-ratelimit-remaining-tokens")
        if remaining_requests is not None or remaining_tokens is not None:
            print(
                f"[llm] groq quota remaining - requests: {remaining_requests}, tokens: {remaining_tokens}",
                file=sys.stderr,
            )
    except Exception:
        pass


def _generate_groq(prompt: str, system: str | None, tools: list[dict] | None, max_tokens: int | None):
    from groq import Groq
    import groq as groq_sdk

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise LLMError("GROQ_API_KEY is not set. Copy .env.example to .env and add your key.")

    client = Groq(api_key=api_key, max_retries=GROQ_MAX_RETRIES)
    kwargs = {"model": GROQ_MODEL, "messages": _groq_messages(system, prompt)}
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if tools:
        kwargs["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema"),
                },
            }
            for t in tools
        ]

    try:
        if GROQ_LOG_RATE_LIMITS:
            raw_response = client.chat.completions.with_raw_response.create(**kwargs)
            _log_groq_rate_limit(raw_response.headers)
            response = raw_response.parse()
        else:
            response = client.chat.completions.create(**kwargs)
    except groq_sdk.AuthenticationError:
        raise LLMError("Invalid Groq API key. Check your .env file.")
    except groq_sdk.RateLimitError:
        raise LLMError("Rate limited by the LLM provider. Wait a moment and try again.")
    except groq_sdk.APIConnectionError:
        raise LLMError("Could not reach the LLM provider. Check your internet connection.")
    except groq_sdk.APIStatusError as e:
        raise LLMError(f"Groq provider error ({e.status_code}): {e.message}")

    message = response.choices[0].message
    tool_calls = []
    for call in message.tool_calls or []:
        tool_calls.append({"name": call.function.name, "input": json.loads(call.function.arguments)})

    return _format_result(text=message.content or "", tool_calls=tool_calls, tools_requested=tools is not None)


def _stream_groq(prompt: str, system: str | None, max_tokens: int | None) -> Iterator[str]:
    from groq import Groq
    import groq as groq_sdk

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise LLMError("GROQ_API_KEY is not set. Copy .env.example to .env and add your key.")

    client = Groq(api_key=api_key, max_retries=GROQ_MAX_RETRIES)
    kwargs = {"model": GROQ_MODEL, "messages": _groq_messages(system, prompt), "stream": True}
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    try:
        if GROQ_LOG_RATE_LIMITS:
            raw_response = client.chat.completions.with_raw_response.create(**kwargs)
            _log_groq_rate_limit(raw_response.headers)
            stream = raw_response.parse()
        else:
            stream = client.chat.completions.create(**kwargs)
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
    except groq_sdk.AuthenticationError:
        raise LLMError("Invalid Groq API key. Check your .env file.")
    except groq_sdk.RateLimitError:
        raise LLMError("Rate limited by the LLM provider. Wait a moment and try again.")
    except groq_sdk.APIConnectionError:
        raise LLMError("Could not reach the LLM provider. Check your internet connection.")
    except groq_sdk.APIStatusError as e:
        raise LLMError(f"Groq provider error ({e.status_code}): {e.message}")


# Every real call site in this app always passes an explicit max_tokens, so
# this is only a defensive fallback - Anthropic's API requires max_tokens on
# every request, unlike Groq/Gemini where it's optional.
_ANTHROPIC_DEFAULT_MAX_TOKENS = 4096


def _anthropic_tools(tools: list[dict] | None) -> list[dict] | None:
    if not tools:
        return None
    return [
        {
            "name": t["name"],
            "description": t.get("description", ""),
            "input_schema": t.get("input_schema"),
        }
        for t in tools
    ]


def _generate_anthropic(prompt: str, system: str | None, tools: list[dict] | None, max_tokens: int | None):
    import anthropic as anthropic_sdk

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise LLMError("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")

    client = anthropic_sdk.Anthropic(api_key=api_key, max_retries=ANTHROPIC_MAX_RETRIES)
    kwargs = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": max_tokens if max_tokens is not None else _ANTHROPIC_DEFAULT_MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system is not None:
        kwargs["system"] = system
    anthropic_tools = _anthropic_tools(tools)
    if anthropic_tools:
        kwargs["tools"] = anthropic_tools

    try:
        response = client.messages.create(**kwargs)
    except anthropic_sdk.AuthenticationError:
        raise LLMError("Invalid Anthropic API key. Check your .env file.")
    except anthropic_sdk.RateLimitError:
        raise LLMError("Rate limited by the LLM provider. Wait a moment and try again.")
    except anthropic_sdk.APIConnectionError:
        raise LLMError("Could not reach the LLM provider. Check your internet connection.")
    except anthropic_sdk.APIStatusError as e:
        raise LLMError(f"Anthropic provider error ({e.status_code}): {e.message}")

    text_parts = []
    tool_calls = []
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append({"name": block.name, "input": block.input})

    return _format_result(text="".join(text_parts), tool_calls=tool_calls, tools_requested=tools is not None)


def _stream_anthropic(prompt: str, system: str | None, max_tokens: int | None) -> Iterator[str]:
    import anthropic as anthropic_sdk

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise LLMError("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")

    client = anthropic_sdk.Anthropic(api_key=api_key, max_retries=ANTHROPIC_MAX_RETRIES)
    kwargs = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": max_tokens if max_tokens is not None else _ANTHROPIC_DEFAULT_MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system is not None:
        kwargs["system"] = system

    try:
        with client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                yield text
    except anthropic_sdk.AuthenticationError:
        raise LLMError("Invalid Anthropic API key. Check your .env file.")
    except anthropic_sdk.RateLimitError:
        raise LLMError("Rate limited by the LLM provider. Wait a moment and try again.")
    except anthropic_sdk.APIConnectionError:
        raise LLMError("Could not reach the LLM provider. Check your internet connection.")
    except anthropic_sdk.APIStatusError as e:
        raise LLMError(f"Anthropic provider error ({e.status_code}): {e.message}")


def _format_result(text: str, tool_calls: list[dict], tools_requested: bool):
    if not tools_requested:
        return text
    return {"text": text, "tool_calls": tool_calls}


def parse_json_object(text: str) -> dict:
    """Best-effort extraction of a JSON object from an LLM response.

    Strips markdown code fences if present. Returns {} if the text isn't
    valid JSON or isn't a JSON object — callers should treat that as
    "nothing extracted", not crash.
    """
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        # A non-empty response that still failed to parse is almost always
        # a completion cut off mid-JSON by max_tokens, not garbage from
        # scratch - logging the length makes that distinguishable at a
        # glance from a genuinely empty response, without changing the
        # return value callers rely on.
        reason = "likely truncated mid-JSON" if cleaned else "empty response"
        print(f"[llm] parse_json_object: could not parse {len(cleaned)}-char response as JSON ({reason})", file=sys.stderr)
        return {}
