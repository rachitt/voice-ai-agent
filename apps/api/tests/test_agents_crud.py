async def test_create_list_get_publish_agent(client, auth_headers):
    r = await client.post(
        "/v1/agents",
        json={"name": "A1", "first_message": "Hi", "system_prompt": "be helpful"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    agent_id = body["id"]
    version_id = body["versions"][0]["id"]
    assert body["published_version_id"] is None

    r = await client.get("/v1/agents", headers=auth_headers)
    assert r.status_code == 200
    assert any(a["id"] == agent_id for a in r.json())

    r = await client.post(
        f"/v1/agents/{agent_id}/publish",
        json={"version_id": version_id, "env": "production"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["published_version_id"] == version_id


async def test_update_bumps_version(client, auth_headers):
    r = await client.post(
        "/v1/agents",
        json={"name": "A2", "first_message": "hi", "system_prompt": "s"},
        headers=auth_headers,
    )
    agent_id = r.json()["id"]

    r = await client.patch(
        f"/v1/agents/{agent_id}",
        json={"first_message": "hello there"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["version"] == 2
