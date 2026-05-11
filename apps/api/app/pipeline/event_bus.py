"""In-process per-call event bus.

Lets one publisher (the web-call WS handler) fan out PipelineEvent JSON
payloads to many subscribers (SSE listeners on /v1/calls/:id/stream).

This is intentionally process-local: it survives a single API worker only.
For multi-worker, swap to Redis pub/sub behind the same interface.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any

# call_id -> set of subscriber queues
_SUBS: dict[str, set[asyncio.Queue[dict[str, Any] | None]]] = defaultdict(set)


def publish(call_id: str, event: dict[str, Any]) -> None:
    """Fan-out a single event to all subscribers for this call.

    Non-blocking: if a subscriber queue is full we drop the event for that
    subscriber rather than back-pressure the publisher.
    """
    for q in list(_SUBS.get(call_id, ())):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


def close(call_id: str) -> None:
    """Signal end-of-stream to all subscribers and forget them."""
    subs = _SUBS.pop(call_id, set())
    for q in subs:
        try:
            q.put_nowait(None)
        except asyncio.QueueFull:
            pass


async def subscribe(call_id: str) -> AsyncIterator[dict[str, Any]]:
    """Async iterator of events for a call. Ends on close()."""
    q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=256)
    _SUBS[call_id].add(q)
    try:
        while True:
            ev = await q.get()
            if ev is None:
                return
            yield ev
    finally:
        _SUBS[call_id].discard(q)
        if not _SUBS[call_id]:
            _SUBS.pop(call_id, None)


def subscriber_count(call_id: str) -> int:
    return len(_SUBS.get(call_id, ()))
