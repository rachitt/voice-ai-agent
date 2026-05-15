"""LLM abstraction over LiteLLM.

LiteLLM gives us an OpenAI-compatible interface across providers (Gemini,
OpenAI, Anthropic, Groq, etc.) so swap is just a model id change.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import litellm

from app.core.config import get_settings
from app.core.logging import log

litellm.drop_params = True
litellm.set_verbose = False

ROLE = {"system", "user", "assistant", "tool"}


@dataclass
class Message:
    role: str
    content: str
    tool_call_id: str | None = None
    name: str | None = None

    def to_litellm(self) -> dict[str, Any]:
        out: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_call_id is not None:
            out["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            out["name"] = self.name
        return out


def _provider_kwargs(model_id: str) -> dict[str, Any]:
    s = get_settings()
    if model_id.startswith("gemini"):
        return {"api_key": s.gemini_api_key}
    return {}


async def complete(
    *,
    model_id: str,
    messages: list[Message],
    tools: list[dict] | None = None,
    temperature: float = 0.3,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Non-streaming completion. Returns OpenAI-shaped response dict."""
    kw = {
        "model": model_id,
        "messages": [m.to_litellm() for m in messages],
        "temperature": temperature,
        **_provider_kwargs(model_id),
    }
    if tools:
        kw["tools"] = tools
    if max_tokens:
        kw["max_tokens"] = max_tokens
    resp = await litellm.acompletion(**kw)
    return resp.model_dump() if hasattr(resp, "model_dump") else resp


async def stream(
    *,
    model_id: str,
    messages: list[Message],
    tools: list[dict] | None = None,
    temperature: float = 0.3,
) -> AsyncIterator[str]:
    """Streaming text deltas. Yields token chunks as they arrive."""
    kw = {
        "model": model_id,
        "messages": [m.to_litellm() for m in messages],
        "temperature": temperature,
        "stream": True,
        **_provider_kwargs(model_id),
    }
    if tools:
        kw["tools"] = tools

    try:
        async for chunk in await litellm.acompletion(**kw):
            choices = chunk.choices if hasattr(chunk, "choices") else chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].delta
            content = delta.content if hasattr(delta, "content") else delta.get("content")
            if content:
                yield content
    except Exception as exc:
        log.exception("llm.stream.error", model=model_id, err=str(exc))
        raise


async def embed(*, model_id: str, texts: list[str]) -> list[list[float]]:
    """Batched embeddings."""
    s = get_settings()
    kw: dict[str, Any] = {"model": model_id, "input": texts}
    if model_id.startswith("text-embedding"):
        kw["api_key"] = s.gemini_api_key or None  # OpenAI fallback handled by LiteLLM env
    resp = await litellm.aembedding(**kw)
    data = resp.get("data") if isinstance(resp, dict) else resp.data
    return [d["embedding"] if isinstance(d, dict) else d.embedding for d in data]
