"""event_bus pub/sub correctness."""
from __future__ import annotations

import asyncio

import pytest

from app.pipeline import event_bus


@pytest.mark.asyncio
async def test_publish_fans_out_to_multiple_subscribers():
    seen_a: list[dict] = []
    seen_b: list[dict] = []

    async def sub(out: list[dict]) -> None:
        async for ev in event_bus.subscribe("call_x"):
            out.append(ev)

    ta = asyncio.create_task(sub(seen_a))
    tb = asyncio.create_task(sub(seen_b))
    await asyncio.sleep(0.05)  # let both subscribe

    event_bus.publish("call_x", {"type": "agent_text", "text": "hi"})
    event_bus.publish("call_x", {"type": "turn_end"})
    await asyncio.sleep(0.05)
    event_bus.close("call_x")
    await asyncio.gather(ta, tb)

    assert [e["type"] for e in seen_a] == ["agent_text", "turn_end"]
    assert seen_a == seen_b


@pytest.mark.asyncio
async def test_close_terminates_subscribers():
    out: list[dict] = []

    async def sub() -> None:
        async for ev in event_bus.subscribe("call_y"):
            out.append(ev)

    t = asyncio.create_task(sub())
    await asyncio.sleep(0.05)
    event_bus.close("call_y")
    await asyncio.wait_for(t, timeout=1.0)
    assert out == []


@pytest.mark.asyncio
async def test_publish_with_no_subscribers_is_noop():
    event_bus.publish("nobody_home", {"type": "ignored"})  # must not raise
    assert event_bus.subscriber_count("nobody_home") == 0
