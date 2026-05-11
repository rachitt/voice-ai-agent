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


async def test_patch_mutates_draft_in_place(client, auth_headers):
    r = await client.post(
        "/v1/agents",
        json={"name": "A2", "first_message": "hi", "system_prompt": "s"},
        headers=auth_headers,
    )
    agent_id = r.json()["id"]
    draft_id = r.json()["versions"][0]["id"]
    assert r.json()["versions"][0]["version"] == 1

    r1 = await client.patch(
        f"/v1/agents/{agent_id}",
        json={"first_message": "hello there"},
        headers=auth_headers,
    )
    assert r1.status_code == 200
    assert r1.json()["id"] == draft_id
    assert r1.json()["version"] == 1
    assert r1.json()["first_message"] == "hello there"

    r2 = await client.patch(
        f"/v1/agents/{agent_id}",
        json={"system_prompt": "updated"},
        headers=auth_headers,
    )
    assert r2.status_code == 200
    assert r2.json()["id"] == draft_id
    assert r2.json()["version"] == 1

    detail = await client.get(f"/v1/agents/{agent_id}", headers=auth_headers)
    assert len(detail.json()["versions"]) == 1


async def test_publish_freezes_draft_and_spawns_new_draft(client, auth_headers):
    r = await client.post(
        "/v1/agents",
        json={"name": "A3", "first_message": "hi"},
        headers=auth_headers,
    )
    agent_id = r.json()["id"]
    v1_id = r.json()["versions"][0]["id"]

    r = await client.post(
        f"/v1/agents/{agent_id}/publish",
        json={"version_id": v1_id, "env": "production"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["published_version_id"] == v1_id
    versions = sorted(body["versions"], key=lambda v: v["version"])
    assert len(versions) == 2
    assert versions[0]["id"] == v1_id
    assert versions[0]["env"] == "production"
    assert versions[1]["env"] == "draft"
    assert versions[1]["version"] == 2

    r = await client.patch(
        f"/v1/agents/{agent_id}",
        json={"first_message": "second take"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["id"] == versions[1]["id"]
    assert r.json()["version"] == 2
