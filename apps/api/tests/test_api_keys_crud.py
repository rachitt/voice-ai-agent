"""Dashboard API key management (session-cookie auth)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.sessions import mint_session
from app.db import models


@pytest.fixture
async def session_user(db_session):
    org = models.Org(name="KeyOrg", slug="key-org")
    db_session.add(org)
    await db_session.flush()
    user = models.User(org_id=org.id, email="dash@example.com", name="Dashy", google_sub="g-key")
    db_session.add(user)
    await db_session.commit()
    token = mint_session(user.id, org.id)
    # Double-submit CSRF: cookie value mirrored as header on writes.
    csrf = "test-csrf-" + token[-8:]
    return {
        "user": user,
        "org": org,
        "cookie": {"voice_session": token, "voice_csrf": csrf},
        "csrf_headers": {"x-csrf-token": csrf},
    }


@pytest.mark.asyncio
async def test_create_returns_raw_key_once(client, session_user):
    r = await client.post(
        "/v1/api-keys",
        json={"name": "dev laptop"},
        cookies=session_user["cookie"],
        headers=session_user["csrf_headers"],
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["key"].startswith("sk_live_")
    assert body["prefix"] == body["key"][:10]
    assert body["name"] == "dev laptop"
    assert body["revoked_at"] is None


@pytest.mark.asyncio
async def test_list_does_not_leak_key(client, session_user):
    await client.post(
        "/v1/api-keys",
        json={"name": "k1"},
        cookies=session_user["cookie"],
        headers=session_user["csrf_headers"],
    )
    r = await client.get("/v1/api-keys", cookies=session_user["cookie"])
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert "key" not in rows[0]
    assert "key_hash" not in rows[0]
    assert rows[0]["name"] == "k1"


@pytest.mark.asyncio
async def test_revoke_blocks_subsequent_use(client, session_user, db_session):
    r = await client.post(
        "/v1/api-keys",
        json={"name": "to-revoke"},
        cookies=session_user["cookie"],
        headers=session_user["csrf_headers"],
    )
    body = r.json()
    raw = body["key"]
    key_id = body["id"]

    # Confirm key works first.
    r = await client.get("/v1/agents", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 200

    r = await client.delete(
        f"/v1/api-keys/{key_id}",
        cookies=session_user["cookie"],
        headers=session_user["csrf_headers"],
    )
    assert r.status_code == 204

    # Reload to confirm soft-revocation.
    db_session.expire_all()
    key = (
        await db_session.execute(select(models.ApiKey).where(models.ApiKey.id == key_id))
    ).scalar_one()
    assert key.revoked_at is not None

    r = await client.get("/v1/agents", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_requires_session_not_api_key(client, session_user, auth_headers):
    # API-key (Authorization) must NOT grant access to the dashboard endpoints.
    r = await client.post("/v1/api-keys", json={"name": "no"}, headers=auth_headers)
    assert r.status_code == 401
    r = await client.get("/v1/api-keys", headers=auth_headers)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_cross_org_isolation(client, session_user, db_session):
    # Create another org+user with their own key — original session should not see it.
    other_org = models.Org(name="Other", slug="other-org")
    db_session.add(other_org)
    await db_session.flush()
    db_session.add(
        models.ApiKey(org_id=other_org.id, name="theirs", prefix="sk_live_x", key_hash="zz")
    )
    await db_session.commit()

    r = await client.get("/v1/api-keys", cookies=session_user["cookie"])
    assert r.status_code == 200
    assert r.json() == []
