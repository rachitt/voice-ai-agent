from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log
from app.db.models import Call, CallEvent, CallStatus
from app.db.session import get_db

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


@router.post("/telnyx", status_code=status.HTTP_204_NO_CONTENT)
async def telnyx_webhook(
    request: Request,
    telnyx_signature_ed25519: str | None = Header(default=None, alias="telnyx-signature-ed25519"),
    telnyx_timestamp: str | None = Header(default=None, alias="telnyx-timestamp"),
    db: AsyncSession = Depends(get_db),
) -> None:
    body = await request.body()
    # TODO: verify ed25519 signature using settings.telnyx_webhook_public_key
    # Telnyx uses ed25519 public-key sigs; deferred to telephony hardening pass.
    _ = (telnyx_signature_ed25519, telnyx_timestamp, body)

    try:
        payload = await request.json()
    except Exception as exc:
        log.warning("telnyx.webhook.bad_json", err=str(exc))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid json") from exc

    data = payload.get("data") or {}
    event_type = data.get("event_type") or "unknown"
    call_payload = data.get("payload") or {}
    cc_id = call_payload.get("call_control_id") or call_payload.get("call_session_id")

    log.info("telnyx.webhook", event=event_type, cc=cc_id)

    if not cc_id:
        return

    call = (
        await db.execute(select(Call).where(Call.provider_call_id == cc_id))
    ).scalar_one_or_none()

    if call:
        db.add(
            CallEvent(
                call_id=call.id,
                at=datetime.now(timezone.utc),
                kind=event_type,
                payload=call_payload,
            )
        )
        if event_type == "call.answered":
            call.status = CallStatus.in_progress
            call.started_at = datetime.now(timezone.utc)
        elif event_type == "call.hangup":
            call.status = CallStatus.completed
            call.ended_at = datetime.now(timezone.utc)
            if call.started_at:
                call.duration_ms = int(
                    (call.ended_at - call.started_at).total_seconds() * 1000
                )
        await db.commit()
