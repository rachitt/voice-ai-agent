async def test_healthz(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_agents_requires_auth(client):
    r = await client.get("/v1/agents")
    assert r.status_code == 401


async def test_agents_rejects_bad_key(client):
    r = await client.get("/v1/agents", headers={"Authorization": "Bearer not-a-real-key"})
    assert r.status_code == 401
