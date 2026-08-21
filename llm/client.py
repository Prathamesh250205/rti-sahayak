"""Thin wrapper around the LLM provider.

Every LLM call in this app goes through generate() (or generate_stream())
so we can swap providers by changing LLM_PROVIDER in .env (gemini | groq) —
no provider-specific code anywhere else in the codebase. If the configured
provider fails, both automatically retry once on the other provider so a
single provider outage doesn't take down the demo.
"""
import json
import os
import re
import sys
from typing import Iterator

from dotenv import load_dotenv

load_dotenv()

PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# Set after each successful generate() call to whichever provider actually
# served it (PROVIDER or its fallback) — lets the UI show a "served by" badge.
LAST_PROVIDER_USED: str | None = None


class LLMError(RuntimeError):
    """Raised when the LLM provider call fails. Message is safe to show in the UI."""


def generate(
    prompt: str,
    system: str | None = None,
    tools: list[dict] | None = None,
    max_tokens: int | None = None,
):
    """Generate a response from the configured LLM provider.

    prompt: the user message.
    system: optional system prompt.
    tools: optional list of {"name", "description", "input_schema"} tool defs.
    max_tokens: optional output cap — set this low for short, simple replies
        to reduce latency; omit for normal-length responses.

    Returns a plain str when tools is None (the common case). When tools is
    given, returns {"text": str, "tool_calls": [{"name", "input"}, ...]} so
    callers can branch on whether the model asked to call a tool.

    Tries PROVIDER first; on failure, automatically retries once on the
    other provider before giving up. Raises LLMError only if both fail —
    callers should catch this and surface it in the UI rather than crash
    the app.
    """
    global LAST_PROVIDER_USED

    if PROVIDER not in ("gemini", "groq"):
        raise LLMError(f"Unknown LLM_PROVIDER '{PROVIDER}'. Use 'gemini' or 'groq'.")

    fallback = "groq" if PROVIDER == "gemini" else "gemini"

    try:
        result = _dispatch(PROVIDER, prompt, system, tools, max_tokens)
        LAST_PROVIDER_USED = PROVIDER
        return result
    except LLMError as primary_error:
        print(f"[llm] {PROVIDER} failed ({primary_error}); retrying on {fallback}...", file=sys.stderr)
        try:
            result = _dispatch(fallback, prompt, system, tools, max_tokens)
            LAST_PROVIDER_USED = fallback
            return result
        except LLMError as fallback_error:
            raise LLMError(
                f"Both LLM providers failed. {PROVIDER}: {primary_error} | {fallback}: {fallback_error}"
            )


def generate_stream(
    prompt: str, system: str | None = None, max_tokens: int | None = None
) -> Iterator[str]:
    """Like generate(), but yields text chunks as they arrive instead of
    blocking for the full response. No tool-calling support (streaming +
    tool calls need response-shape handling this app doesn't use).

    Tries PROVIDER first. Falls back to the other provider only if the
    primary fails before yielding any content — once a stream has started
    delivering text, a mid-stream failure surfaces as LLMError rather than
    silently restarting on the other provider with a half-shown answer.
    """
    global LAST_PROVIDER_USED

    if PROVIDER not in ("gemini", "groq"):
        raise LLMError(f"Unknown LLM_PROVIDER '{PROVIDER}'. Use 'gemini' or 'groq'.")

    fallback = "groq" if PROVIDER == "gemini" else "gemini"

    try:
        yielded_any = False
        for chunk in _dispatch_stream(PROVIDER, prompt, system, max_tokens):
            yielded_any = True
            yield chunk
        LAST_PROVIDER_USED = PROVIDER
    except LLMError as primary_error:
        if yielded_any:
            raise
        print(f"[llm] {PROVIDER} failed ({primary_error}); retrying on {fallback}...", file=sys.stderr)
        for chunk in _dispatch_stream(fallback, prompt, system, max_tokens):
            yield chunk
        LAST_PROVIDER_USED = fallback


def _dispatch(provider: str, prompt: str, system: str | None, tools: list[dict] | None, max_tokens: int | None):
    if provider == "gemini":
        return _generate_gemini(prompt, system, tools, max_tokens)
    return _generate_groq(prompt, system, tools, max_tokens)


def _dispatch_stream(provider: str, prompt: str, system: str | None, max_tokens: int | None) -> Iterator[str]:
    if provider == "gemini":
        return _stream_gemini(prompt, system, max_tokens)
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


def _generate_groq(prompt: str, system: str | None, tools: list[dict] | None, max_tokens: int | None):
    from groq import Groq
    import groq as groq_sdk

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise LLMError("GROQ_API_KEY is not set. Copy .env.example to .env and add your key.")

    client = Groq(api_key=api_key)
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

    client = Groq(api_key=api_key)
    kwargs = {"model": GROQ_MODEL, "messages": _groq_messages(system, prompt), "stream": True}
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    try:
        for chunk in client.chat.completions.create(**kwargs):
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
