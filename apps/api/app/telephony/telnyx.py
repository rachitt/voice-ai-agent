from __future__ import annotations

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.core.logging import log

TELNYX_API = "https://api.telnyx.com/v2"


class TelnyxClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = httpx.AsyncClient(
            base_url=TELNYX_API,
            headers={"Authorization": f"Bearer {self.settings.telnyx_api_key}"},
            timeout=15.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=5), reraise=True)
    async def buy_number(self, e164: str) -> dict:
        r = await self._client.post(
            "/number_orders",
            json={"phone_numbers": [{"phone_number": e164}]},
        )
        r.raise_for_status()
        return r.json()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=5), reraise=True)
    async def initiate_call(
        self, *, to: str, from_: str, webhook_url: str, stream_url: str
    ) -> dict:
        body = {
            "connection_id": self.settings.telnyx_connection_id,
            "to": to,
            "from": from_,
            "webhook_url": webhook_url,
            "stream_url": stream_url,
            "stream_track": "both_tracks",
            "answering_machine_detection": "premium",
        }
        r = await self._client.post("/calls", json=body)
        r.raise_for_status()
        return r.json()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=5), reraise=True)
    async def answer(
        self,
        call_control_id: str,
        *,
        stream_url: str | None = None,
        stream_track: str = "both_tracks",
    ) -> dict:
        body: dict = {}
        if stream_url:
            body["stream_url"] = stream_url
            body["stream_track"] = stream_track
        r = await self._client.post(
            f"/calls/{call_control_id}/actions/answer", json=body
        )
        r.raise_for_status()
        return r.json()

    async def hangup(self, call_control_id: str) -> None:
        r = await self._client.post(f"/calls/{call_control_id}/actions/hangup")
        if r.status_code >= 400:
            log.warning("telnyx.hangup.fail", status=r.status_code, body=r.text)

    async def transfer(self, call_control_id: str, *, to: str, from_: str) -> None:
        r = await self._client.post(
            f"/calls/{call_control_id}/actions/transfer",
            json={"to": to, "from": from_},
        )
        r.raise_for_status()

    async def send_dtmf(self, call_control_id: str, digits: str) -> None:
        r = await self._client.post(
            f"/calls/{call_control_id}/actions/send_dtmf", json={"digits": digits}
        )
        r.raise_for_status()
