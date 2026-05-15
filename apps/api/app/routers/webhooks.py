from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import log
from app.db.models import (
    Agent,
    Call,
    CallDirection,
    CallEvent,
    CallStatus,
    PhoneNumber,
)
from app.db.session import get_db
from app.pipeline.web_session import mint_ws_token
from app.telephony.signature import WebhookSignatureError, verify_telnyx
from app.telephony.telnyx import TelnyxClient

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


def _telnyx_client_factory() -> TelnyxClient:
    """Indirection so tests can patch this with a fake."""
    return TelnyxClient()


@router.post("/telnyx", status_code=status.HTTP_204_NO_CONTENT)
async def telnyx_webhook(
    request: Request,
    telnyx_signature_ed25519: str | None = Header(default=None, alias="telnyx-signature-ed25519"),
    telnyx_timestamp: str | None = Header(default=None, alias="telnyx-timestamp"),
    db: AsyncSession = Depends(get_db),
) -> None:
    body = await request.body()
    if get_settings().telnyx_webhook_public_key:
        try:
            verify_telnyx(
                raw_body=body,
                signature_b64=telnyx_signature_ed25519,
                timestamp=telnyx_timestamp,
            )
        except WebhookSignatureError as exc:
            log.warning("telnyx.webhook.bad_signature", err=str(exc))
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    try:
        payload = await request.json()
    except Exception as exc:
        log.warning("telnyx.webhook.bad_json", err=str(exc))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid json") from exc

    data = payload.get("data") or {}
    event_type = data.get("event_type") or "unknown"
    call_payload = data.get("payload") or {}
    cc_id = call_payload.get("call_control_id") or call_payload.get("call_session_id")

    log.info("telnyx.webhook", event_type=event_type, cc=cc_id)

    if not cc_id:
        return

    # Inbound call arrival: lookup phone_number → agent, create Call, answer w/ stream.
    if event_type == "call.initiated" and (call_payload.get("direction") == "incoming"):
        existing = (
            await db.execute(select(Call).where(Call.provider_call_id == cc_id))
        ).scalar_one_or_none()
        if existing is None:
            await _handle_inbound_initiated(db, call_payload, cc_id)
        return

    call = (
        await db.execute(select(Call).where(Call.provider_call_id == cc_id))
    ).scalar_one_or_none()

    if call:
        db.add(
            CallEvent(
                call_id=call.id,
                at=datetime.now(UTC),
                kind=event_type,
                payload=call_payload,
            )
        )
        if event_type == "call.answered":
            call.status = CallStatus.in_progress
            call.started_at = datetime.now(UTC)
        elif event_type == "call.hangup":
            call.status = CallStatus.completed
            call.ended_at = datetime.now(UTC)
            if call.started_at:
                call.duration_ms = int((call.ended_at - call.started_at).total_seconds() * 1000)
        await db.commit()


async def _handle_inbound_initiated(db: AsyncSession, call_payload: dict, cc_id: str) -> None:
    """Provision Call row + answer with media stream for an inbound PSTN call."""
    to_e164 = call_payload.get("to")
    from_e164 = call_payload.get("from")
    if not to_e164:
        log.warning("telnyx.inbound.no_to", cc=cc_id)
        return

    pn = (
        await db.execute(select(PhoneNumber).where(PhoneNumber.e164 == to_e164))
    ).scalar_one_or_none()
    if pn is None or not pn.agent_id:
        log.warning("telnyx.inbound.no_agent_binding", to=to_e164, cc=cc_id)
        return

    agent = (await db.execute(select(Agent).where(Agent.id == pn.agent_id))).scalar_one_or_none()
    if agent is None:
        log.warning("telnyx.inbound.agent_missing", agent_id=pn.agent_id, cc=cc_id)
        return

    call = Call(
        org_id=pn.org_id,
        agent_id=agent.id,
        agent_version_id=agent.published_version_id,
        phone_number_id=pn.id,
        direction=CallDirection.inbound,
        status=CallStatus.ringing,
        from_number=from_e164,
        to_number=to_e164,
        provider_call_id=cc_id,
    )
    db.add(call)
    await db.flush()
    db.add(
        CallEvent(
            call_id=call.id,
            at=datetime.now(UTC),
            kind="call.initiated",
            payload=call_payload,
        )
    )
    await db.commit()
    await db.refresh(call)

    settings = get_settings()
    token = mint_ws_token(call.id)
    stream_url = (
        f"{settings.public_ws_base_url}/v1/telephony/telnyx/media?call_id={call.id}&token={token}"
    )

    telnyx = _telnyx_client_factory()
    try:
        await telnyx.answer(cc_id, stream_url=stream_url)
    except Exception as exc:
        log.exception("telnyx.inbound.answer_failed", cc=cc_id, err=str(exc))
        call.status = CallStatus.failed
        await db.commit()
        return
    finally:
        await telnyx.aclose()
