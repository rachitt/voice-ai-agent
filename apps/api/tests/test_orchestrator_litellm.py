"""orchestrator.litellm_turn — accumulates tool_call deltas across chunks."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.pipeline.orchestrator import TextChunk, ToolCall, TurnComplete, litellm_turn


async def _drain(it):
    return [e async for e in it]


def _chunk(*, content=None, tool_calls=None, finish_reason=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


def _tc(*, idx=0, id=None, name=None, args=None):
    fn = SimpleNamespace(name=name, arguments=args) if (name or args) else None
    return SimpleNamespace(index=idx, id=id, function=fn)


@pytest.mark.asyncio
async def test_litellm_turn_text_only(monkeypatch):
    async def gen():
        yield _chunk(content="Hel")
        yield _chunk(content="lo")
        yield _chunk(finish_reason="stop")

    async def fake_acompletion(**kw):
        assert kw["stream"] is True
        return gen()

    import litellm as _lite

    monkeypatch.setattr(_lite, "acompletion", fake_acompletion)
    out = await _drain(litellm_turn(messages=[], tools=None, model_id="gpt"))
    assert [type(x).__name__ for x in out] == ["TextChunk", "TextChunk", "TurnComplete"]
    assert [x.text for x in out if isinstance(x, TextChunk)] == ["Hel", "lo"]
    assert isinstance(out[-1], TurnComplete)
    assert out[-1].finish_reason == "stop"
    assert out[-1].tool_calls == []


@pytest.mark.asyncio
async def test_litellm_turn_accumulates_tool_call_args(monkeypatch):
    """Tool-call deltas come in fragments — name once, args streamed in pieces."""

    async def gen():
        yield _chunk(tool_calls=[_tc(idx=0, id="tc_1", name="end_call")])
        yield _chunk(tool_calls=[_tc(idx=0, args='{"reaso')])
        yield _chunk(tool_calls=[_tc(idx=0, args='n":"done"}')])
        yield _chunk(finish_reason="tool_calls")

    async def fake_acompletion(**kw):
        return gen()

    import litellm as _lite

    monkeypatch.setattr(_lite, "acompletion", fake_acompletion)
    out = await _drain(litellm_turn(messages=[], tools=[{}], model_id="gpt"))
    final = out[-1]
    assert isinstance(final, TurnComplete)
    assert final.finish_reason == "tool_calls"
    assert len(final.tool_calls) == 1
    tc = final.tool_calls[0]
    assert isinstance(tc, ToolCall)
    assert tc.id == "tc_1"
    assert tc.name == "end_call"
    assert tc.arguments == {"reason": "done"}


@pytest.mark.asyncio
async def test_litellm_turn_handles_dict_chunks(monkeypatch):
    """Some providers yield plain dicts instead of objects — duck-type paths."""

    async def gen():
        yield {
            "choices": [
                {
                    "delta": {
                        "content": None,
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "tc_dict",
                                "function": {"name": "send_dtmf", "arguments": '{"d":"1"}'},
                            }
                        ],
                    },
                    "finish_reason": None,
                }
            ]
        }
        yield {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}

    async def fake_acompletion(**kw):
        return gen()

    import litellm as _lite

    monkeypatch.setattr(_lite, "acompletion", fake_acompletion)
    out = await _drain(litellm_turn(messages=[], tools=[{}], model_id="gpt"))
    final = out[-1]
    assert isinstance(final, TurnComplete)
    assert len(final.tool_calls) == 1
    assert final.tool_calls[0].name == "send_dtmf"
    assert final.tool_calls[0].arguments == {"d": "1"}


@pytest.mark.asyncio
async def test_litellm_turn_malformed_tool_args_kept_raw(monkeypatch):
    async def gen():
        yield _chunk(tool_calls=[_tc(idx=0, id="tc_x", name="t", args='not-json')])
        yield _chunk(finish_reason="tool_calls")

    async def fake_acompletion(**kw):
        return gen()

    import litellm as _lite

    monkeypatch.setattr(_lite, "acompletion", fake_acompletion)
    out = await _drain(litellm_turn(messages=[], tools=[{}], model_id="gpt"))
    assert out[-1].tool_calls[0].arguments == {"_raw": "not-json"}


@pytest.mark.asyncio
async def test_litellm_turn_skips_empty_choices(monkeypatch):
    async def gen():
        yield {"choices": []}
        yield _chunk(content="ok")
        yield _chunk(finish_reason="stop")

    async def fake_acompletion(**kw):
        return gen()

    import litellm as _lite

    monkeypatch.setattr(_lite, "acompletion", fake_acompletion)
    out = await _drain(litellm_turn(messages=[], tools=None, model_id="gpt"))
    assert any(isinstance(e, TextChunk) and e.text == "ok" for e in out)


@pytest.mark.asyncio
async def test_litellm_turn_default_tool_id_when_missing(monkeypatch):
    """If the provider never sends a tool-call id, we fabricate one."""

    async def gen():
        yield _chunk(tool_calls=[_tc(idx=0, name="x", args='{}')])
        yield _chunk(finish_reason="tool_calls")

    async def fake_acompletion(**kw):
        return gen()

    import litellm as _lite

    monkeypatch.setattr(_lite, "acompletion", fake_acompletion)
    out = await _drain(litellm_turn(messages=[], tools=[{}], model_id="gpt"))
    assert out[-1].tool_calls[0].id == "call_0"


@pytest.mark.asyncio
async def test_litellm_turn_passes_gemini_api_key(monkeypatch):
    """When model_id starts with gemini, settings.gemini_api_key is added."""
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    monkeypatch.setenv("VOICE_GEMINI_API_KEY", "g-key")
    captured: dict = {}

    async def gen():
        yield _chunk(finish_reason="stop")

    async def fake_acompletion(**kw):
        captured.update(kw)
        return gen()

    import litellm as _lite

    monkeypatch.setattr(_lite, "acompletion", fake_acompletion)
    await _drain(litellm_turn(messages=[], tools=None, model_id="gemini/gemini-3.1-flash-lite"))
    assert captured.get("api_key") == "g-key"
    cfg.get_settings.cache_clear()
