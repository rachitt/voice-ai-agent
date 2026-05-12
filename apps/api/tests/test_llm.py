"""LLM wrapper: complete, stream, embed, Message + provider kwargs."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.pipeline import llm as llm_mod


def test_message_to_litellm_minimal():
    m = llm_mod.Message(role="user", content="hi")
    assert m.to_litellm() == {"role": "user", "content": "hi"}


def test_message_to_litellm_with_tool_call():
    m = llm_mod.Message(
        role="tool", content="ok", tool_call_id="tc_1", name="end_call"
    )
    assert m.to_litellm() == {
        "role": "tool",
        "content": "ok",
        "tool_call_id": "tc_1",
        "name": "end_call",
    }


def test_provider_kwargs_gemini(monkeypatch):
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    monkeypatch.setenv("VOICE_GEMINI_API_KEY", "gem-xyz")
    assert llm_mod._provider_kwargs("gemini-2.0-flash") == {"api_key": "gem-xyz"}
    cfg.get_settings.cache_clear()


def test_provider_kwargs_non_gemini():
    assert llm_mod._provider_kwargs("gpt-4o-mini") == {}


@pytest.mark.asyncio
async def test_complete_returns_model_dump(monkeypatch):
    captured: dict[str, Any] = {}

    class _Resp:
        def model_dump(self):
            return {"id": "r_1", "choices": [{"message": {"content": "hi"}}]}

    async def fake_acompletion(**kw):
        captured.update(kw)
        return _Resp()

    monkeypatch.setattr(llm_mod.litellm, "acompletion", fake_acompletion)
    out = await llm_mod.complete(
        model_id="gpt-4o-mini",
        messages=[llm_mod.Message(role="user", content="hello")],
        tools=[{"type": "function", "function": {"name": "x"}}],
        max_tokens=256,
        temperature=0.7,
    )
    assert out == {"id": "r_1", "choices": [{"message": {"content": "hi"}}]}
    assert captured["model"] == "gpt-4o-mini"
    assert captured["temperature"] == 0.7
    assert captured["max_tokens"] == 256
    assert captured["tools"][0]["function"]["name"] == "x"


@pytest.mark.asyncio
async def test_complete_returns_raw_dict_when_no_model_dump(monkeypatch):
    async def fake_acompletion(**kw):
        return {"id": "raw", "choices": []}

    monkeypatch.setattr(llm_mod.litellm, "acompletion", fake_acompletion)
    out = await llm_mod.complete(
        model_id="other",
        messages=[llm_mod.Message(role="user", content="hi")],
    )
    assert out == {"id": "raw", "choices": []}


@pytest.mark.asyncio
async def test_stream_yields_text_deltas(monkeypatch):
    async def gen():
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="Hel"))]
        )
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="lo"))]
        )
        yield SimpleNamespace(choices=[])  # empty choices skipped
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=""))]
        )  # empty content skipped

    async def fake_acompletion(**kw):
        assert kw.get("stream") is True
        return gen()

    monkeypatch.setattr(llm_mod.litellm, "acompletion", fake_acompletion)
    out: list[str] = []
    async for tok in llm_mod.stream(
        model_id="gemini-2.0-flash",
        messages=[llm_mod.Message(role="user", content="hi")],
        tools=[{"type": "function", "function": {"name": "x"}}],
    ):
        out.append(tok)
    assert out == ["Hel", "lo"]


@pytest.mark.asyncio
async def test_stream_reraises_on_error(monkeypatch):
    async def fake_acompletion(**kw):
        raise RuntimeError("upstream 500")

    monkeypatch.setattr(llm_mod.litellm, "acompletion", fake_acompletion)
    with pytest.raises(RuntimeError, match="upstream 500"):
        async for _ in llm_mod.stream(
            model_id="m", messages=[llm_mod.Message(role="user", content="x")]
        ):
            pass


@pytest.mark.asyncio
async def test_embed_handles_dict_response(monkeypatch):
    async def fake_aembedding(**kw):
        assert kw["input"] == ["a", "b"]
        return {"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]}

    monkeypatch.setattr(llm_mod.litellm, "aembedding", fake_aembedding)
    out = await llm_mod.embed(model_id="text-embedding-3-small", texts=["a", "b"])
    assert out == [[0.1, 0.2], [0.3, 0.4]]


@pytest.mark.asyncio
async def test_embed_handles_object_response(monkeypatch):
    class _D:
        def __init__(self, e): self.embedding = e

    class _R:
        data = [_D([1.0]), _D([2.0])]

    async def fake_aembedding(**kw):
        return _R()

    monkeypatch.setattr(llm_mod.litellm, "aembedding", fake_aembedding)
    out = await llm_mod.embed(model_id="non-text", texts=["x", "y"])
    assert out == [[1.0], [2.0]]
