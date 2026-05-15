"""Knowledge base query endpoint — embedding-stubbed for offline runs."""

from __future__ import annotations

import pytest

from app.db import models


def _stub_embed(_dim: int = 1536):
    """Return a deterministic embed() stub keyed by query token presence.

    Chunks whose text contains a word from the query get a vector that
    perfectly matches the query vector; everything else gets orthogonal
    noise. Lets `cosine_distance` rank hits without hitting OpenAI.
    """

    async def fake_embed(*, model_id: str, texts: list[str]):  # noqa: ARG001
        vecs = []
        for t in texts:
            vec = [0.0] * _dim
            # Hash tokens into the first 32 slots — repeatable across runs.
            for w in t.lower().split():
                w = "".join(c for c in w if c.isalnum())
                if not w:
                    continue
                vec[hash(w) % 32] += 1.0
            # L2-normalize so cosine_distance is well-defined.
            mag = sum(v * v for v in vec) ** 0.5 or 1.0
            vecs.append([v / mag for v in vec])
        return vecs

    return fake_embed


@pytest.fixture
def patch_embed(monkeypatch):
    from app.kb import store as kb_store

    monkeypatch.setattr(kb_store, "embed", _stub_embed())


@pytest.mark.asyncio
async def test_query_returns_hits_sorted_by_score(client, auth_headers, db_session, patch_embed):
    from sqlalchemy import select

    from app.core.security import hash_api_key

    bearer = auth_headers["Authorization"].split(" ", 1)[1]
    org_row = (
        await db_session.execute(
            select(models.ApiKey, models.Org)
            .join(models.Org, models.Org.id == models.ApiKey.org_id)
            .where(models.ApiKey.key_hash == hash_api_key(bearer))
        )
    ).first()
    _, org = org_row

    # Build a KB w/ two chunks. One matches the query, one doesn't.
    kb = models.KnowledgeBase(org_id=org.id, name="docs")
    db_session.add(kb)
    await db_session.flush()

    src = models.KbSource(kb_id=kb.id, name="faq.md", kind="md", status="ready")
    db_session.add(src)
    await db_session.flush()

    # Pre-compute the embeddings using the stub so DB rows match search vector.
    from app.kb.store import embed as _live_embed  # post-patch this is the stub

    chunks = [
        ("Refund policy is 30 days.", 0),
        ("The cafeteria is on the second floor.", 1),
    ]
    vecs = await _live_embed(model_id=kb.embedding_model, texts=[t for t, _ in chunks])
    for (text, idx), vec in zip(chunks, vecs, strict=True):
        db_session.add(
            models.KbChunk(
                kb_id=kb.id,
                source_id=src.id,
                chunk_index=idx,
                text=text,
                embedding=vec,
            )
        )
    await db_session.commit()

    r = await client.post(
        f"/v1/knowledge-bases/{kb.id}/query",
        headers=auth_headers,
        json={"query": "refund policy", "top_k": 5},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["elapsed_ms"] >= 0
    hits = body["hits"]
    assert hits, "expected at least one hit"
    assert hits[0]["text"].startswith("Refund policy")
    assert hits[0]["source_name"] == "faq.md"


@pytest.mark.asyncio
async def test_query_empty_string_returns_empty(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.core.security import hash_api_key

    bearer = auth_headers["Authorization"].split(" ", 1)[1]
    org_row = (
        await db_session.execute(
            select(models.ApiKey, models.Org)
            .join(models.Org, models.Org.id == models.ApiKey.org_id)
            .where(models.ApiKey.key_hash == hash_api_key(bearer))
        )
    ).first()
    _, org = org_row
    kb = models.KnowledgeBase(org_id=org.id, name="empty")
    db_session.add(kb)
    await db_session.commit()

    r = await client.post(
        f"/v1/knowledge-bases/{kb.id}/query",
        headers=auth_headers,
        json={"query": "   ", "top_k": 3},
    )
    assert r.status_code == 200
    assert r.json()["hits"] == []


@pytest.mark.asyncio
async def test_query_other_org_kb_404(client, auth_headers):
    r = await client.post(
        "/v1/knowledge-bases/kb_does_not_exist/query",
        headers=auth_headers,
        json={"query": "x"},
    )
    assert r.status_code == 404
