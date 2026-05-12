"""Built-in tools — handler paths: end_call, transfer_call, send_dtmf,
leave_voicemail, extract_data, plus dispatch error/unknown paths."""

from __future__ import annotations

import pytest

from app.db import models
from app.tools.builtins import REGISTRY, ToolContext, builtin_definitions, dispatch


class FakeTelnyx:
    def __init__(self) -> None:
        self.hangups: list[str] = []
        self.transfers: list[tuple[str, str, str]] = []
        self.dtmfs: list[tuple[str, str]] = []
        self.fail_hangup = False

    async def hangup(self, cc: str) -> None:
        if self.fail_hangup:
            raise RuntimeError("carrier 500")
        self.hangups.append(cc)

    async def transfer(self, cc: str, *, to: str, from_: str) -> None:
        self.transfers.append((cc, to, from_))

    async def send_dtmf(self, cc: str, digits: str) -> None:
        self.dtmfs.append((cc, digits))


async def _make_call(db_session, *, provider_call_id: str | None = "cc_x", to_number="+15551234"):
    org = models.Org(name="O", slug=f"o-{provider_call_id or 'none'}")
    db_session.add(org)
    await db_session.flush()
    agent = models.Agent(org_id=org.id, name="A")
    db_session.add(agent)
    await db_session.flush()
    call = models.Call(
        org_id=org.id,
        agent_id=agent.id,
        direction="outbound",
        status="in_progress",
        provider_call_id=provider_call_id,
        to_number=to_number,
        dynamic_variables={},
    )
    db_session.add(call)
    await db_session.commit()
    return call


def test_all_builtins_registered():
    names = {d["function"]["name"] for d in builtin_definitions()}
    assert {"end_call", "transfer_call", "send_dtmf", "leave_voicemail", "kb_lookup", "extract_data"} <= names


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_returns_error(db_session):
    call = await _make_call(db_session)
    ctx = ToolContext(call=call, db=db_session, args={})
    res = await dispatch("does_not_exist", ctx)
    assert res == {"error": "unknown_tool:does_not_exist"}


@pytest.mark.asyncio
async def test_dispatch_handler_exception_returns_tool_failed(db_session, monkeypatch):
    call = await _make_call(db_session)

    async def boom(ctx):  # type: ignore[no-untyped-def]
        raise RuntimeError("kaboom")

    REGISTRY["__boom__"] = {"definition": {}, "handler": boom}
    try:
        res = await dispatch("__boom__", ToolContext(call=call, db=db_session, args={}))
        assert res["error"] == "tool_failed"
        assert "kaboom" in res["detail"]
    finally:
        REGISTRY.pop("__boom__", None)


@pytest.mark.asyncio
async def test_end_call_marks_completed_and_hangs_up(db_session):
    call = await _make_call(db_session)
    tx = FakeTelnyx()
    res = await dispatch("end_call", ToolContext(call=call, db=db_session, telnyx=tx, args={}))
    assert res == {"status": "ended"}
    assert call.status == models.CallStatus.completed
    assert call.ended_at is not None
    assert tx.hangups == ["cc_x"]


@pytest.mark.asyncio
async def test_end_call_without_telnyx_still_completes(db_session):
    call = await _make_call(db_session, provider_call_id=None)
    res = await dispatch("end_call", ToolContext(call=call, db=db_session, args={}))
    assert res == {"status": "ended"}
    assert call.status == models.CallStatus.completed


@pytest.mark.asyncio
async def test_transfer_call_requires_to(db_session):
    call = await _make_call(db_session)
    tx = FakeTelnyx()
    res = await dispatch(
        "transfer_call", ToolContext(call=call, db=db_session, telnyx=tx, args={})
    )
    assert res == {"error": "missing_to"}
    assert tx.transfers == []


@pytest.mark.asyncio
async def test_transfer_call_dispatches_to_telnyx(db_session):
    call = await _make_call(db_session)
    tx = FakeTelnyx()
    res = await dispatch(
        "transfer_call",
        ToolContext(
            call=call,
            db=db_session,
            telnyx=tx,
            args={"to": "+15559999", "summary": "VIP"},
        ),
    )
    assert res == {"transferred_to": "+15559999", "summary": "VIP"}
    assert tx.transfers == [("cc_x", "+15559999", "+15551234")]


@pytest.mark.asyncio
async def test_send_dtmf_requires_digits(db_session):
    call = await _make_call(db_session)
    res = await dispatch("send_dtmf", ToolContext(call=call, db=db_session, args={}))
    assert res == {"error": "missing_digits"}


@pytest.mark.asyncio
async def test_send_dtmf_dispatches(db_session):
    call = await _make_call(db_session)
    tx = FakeTelnyx()
    res = await dispatch(
        "send_dtmf",
        ToolContext(call=call, db=db_session, telnyx=tx, args={"digits": "5678"}),
    )
    assert res == {"sent": "5678"}
    assert tx.dtmfs == [("cc_x", "5678")]


@pytest.mark.asyncio
async def test_leave_voicemail_persists_and_ends(db_session):
    call = await _make_call(db_session)
    tx = FakeTelnyx()
    res = await dispatch(
        "leave_voicemail",
        ToolContext(
            call=call,
            db=db_session,
            telnyx=tx,
            args={"message": "Hi there — please call back."},
        ),
    )
    assert res["left"] is True
    assert res["ended"] is True
    assert res["message"] == "Hi there — please call back."
    assert call.status == models.CallStatus.completed
    assert call.dynamic_variables["voicemail_message"] == "Hi there — please call back."
    assert "voicemail_left_at" in call.dynamic_variables
    assert tx.hangups == ["cc_x"]


@pytest.mark.asyncio
async def test_leave_voicemail_truncates_long_message(db_session):
    call = await _make_call(db_session, provider_call_id=None)
    long_msg = "x" * 5000
    res = await dispatch(
        "leave_voicemail",
        ToolContext(call=call, db=db_session, args={"message": long_msg}),
    )
    assert len(res["message"]) == 1000


@pytest.mark.asyncio
async def test_leave_voicemail_swallows_telnyx_failure(db_session):
    call = await _make_call(db_session)
    tx = FakeTelnyx()
    tx.fail_hangup = True
    res = await dispatch(
        "leave_voicemail",
        ToolContext(call=call, db=db_session, telnyx=tx, args={"message": "bye"}),
    )
    # Still considered completed; hangup error logged.
    assert res["ended"] is True
    assert call.status == models.CallStatus.completed


@pytest.mark.asyncio
async def test_extract_data_merges_dict(db_session):
    call = await _make_call(db_session)
    call.dynamic_variables = {"existing": "v"}
    res = await dispatch(
        "extract_data",
        ToolContext(call=call, db=db_session, args={"data": {"name": "Ada", "tier": "gold"}}),
    )
    assert res["extracted"] == {"name": "Ada", "tier": "gold"}
    assert call.dynamic_variables == {"existing": "v", "name": "Ada", "tier": "gold"}


@pytest.mark.asyncio
async def test_extract_data_parses_json_string(db_session):
    call = await _make_call(db_session)
    res = await dispatch(
        "extract_data",
        ToolContext(call=call, db=db_session, args={"data": '{"a": 1}'}),
    )
    assert res["extracted"] == {"a": 1}
    assert call.dynamic_variables["a"] == 1


@pytest.mark.asyncio
async def test_extract_data_rejects_non_object(db_session):
    call = await _make_call(db_session)
    res = await dispatch(
        "extract_data",
        ToolContext(call=call, db=db_session, args={"data": "not-json"}),
    )
    assert res == {"error": "data_not_object"}
