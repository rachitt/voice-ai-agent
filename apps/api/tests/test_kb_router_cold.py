"""Cold-spot coverage for the knowledge_bases router:
- upload 404 for unknown kb
- upload extract failure → 422
- upload ingest failure → 502 with status='error' persisted
- query returns empty hits when search() yields nothing
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_upload_404_for_unknown_kb(client, auth_headers):
    """Upload to a non-existent kb_id should 404 before any IO."""
    files = {"file": ("policy.txt", b"hello world", "text/plain")}
    r = await client.post(
        "/v1/knowledge-bases/kb_missing/sources/upload",
        files=files,
        headers=auth_headers,
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_upload_extract_failure_422(client, auth_headers, monkeypatch):
    """When extract_text raises, the route 422s + bubbles the error string."""
    from app.routers import knowledge_bases as kb_router

    def boom(_data: bytes, *, kind: str) -> str:  # noqa: ARG001
        raise ValueError("corrupt pdf bytes")

    monkeypatch.setattr(kb_router, "extract_text", boom)

    r = await client.post("/v1/knowledge-bases", json={"name": "ExFail"}, headers=auth_headers)
    kb_id = r.json()["id"]
    files = {"file": ("doc.txt", b"some text", "text/plain")}
    r = await client.post(
        f"/v1/knowledge-bases/{kb_id}/sources/upload",
        files=files,
        headers=auth_headers,
    )
    assert r.status_code == 422, r.text
    assert "corrupt pdf" in r.text


@pytest.mark.asyncio
async def test_upload_ingest_failure_502_marks_source_error(
    client, auth_headers, monkeypatch
):
    """When ingest_source_text raises, status='error' is persisted and the
    route 502s. Subsequent list_sources should reflect the error state."""
    from app.routers import knowledge_bases as kb_router

    async def fail_ingest(*_a, **_k):
        raise RuntimeError("embedding provider down")

    monkeypatch.setattr(kb_router, "ingest_source_text", fail_ingest)

    r = await client.post("/v1/knowledge-bases", json={"name": "IngFail"}, headers=auth_headers)
    kb_id = r.json()["id"]
    files = {"file": ("doc.txt", b"some text content here", "text/plain")}
    r = await client.post(
        f"/v1/knowledge-bases/{kb_id}/sources/upload",
        files=files,
        headers=auth_headers,
    )
    assert r.status_code == 502, r.text
    assert "embedding provider down" in r.text

    lst = await client.get(f"/v1/knowledge-bases/{kb_id}/sources", headers=auth_headers)
    assert lst.status_code == 200
    rows = lst.json()
    assert rows and rows[0]["status"] == "error"
    assert "embedding provider down" in (rows[0]["error"] or "")


@pytest.mark.asyncio
async def test_query_returns_empty_hits_when_search_yields_none(
    client, auth_headers, monkeypatch
):
    """`search()` returning [] hits the early empty-hits return branch."""
    from app.routers import knowledge_bases as kb_router

    async def empty_search(*_a, **_k):
        return []

    monkeypatch.setattr(kb_router, "search", empty_search)

    r = await client.post("/v1/knowledge-bases", json={"name": "EmptyHits"}, headers=auth_headers)
    kb_id = r.json()["id"]
    r = await client.post(
        f"/v1/knowledge-bases/{kb_id}/query",
        headers=auth_headers,
        json={"query": "anything", "top_k": 3},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["hits"] == []
    assert "elapsed_ms" in body
