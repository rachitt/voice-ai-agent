"""Server-side analysis_plan validation."""

from __future__ import annotations

import pytest

from app.schemas.analysis_plan_validator import validate_analysis_plan


def test_none_is_valid():
    assert validate_analysis_plan(None) == []


def test_empty_dict_is_valid():
    assert validate_analysis_plan({}) == []


def test_valid_full_plan():
    plan = {
        "summary_prompt": "summarize the call",
        "success_prompt": "user booked a meeting",
        "structured_data_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        },
    }
    assert validate_analysis_plan(plan) == []


def test_non_dict_plan_rejected():
    assert validate_analysis_plan("not a dict") == [  # type: ignore[arg-type]
        "analysis_plan must be an object"
    ]


def test_prompt_type_errors():
    errors = validate_analysis_plan({"summary_prompt": 123, "success_prompt": ["nope"]})
    assert "summary_prompt must be a string" in errors
    assert "success_prompt must be a string" in errors


def test_invalid_schema_shape():
    errors = validate_analysis_plan({"structured_data_schema": "not an object"})
    assert errors and "structured_data_schema must be an object" in errors[0]


def test_invalid_schema_keywords():
    errors = validate_analysis_plan(
        {"structured_data_schema": {"type": "object", "properties": "should be object"}}
    )
    assert errors
    assert "structured_data_schema invalid" in errors[0]


@pytest.mark.asyncio
async def test_patch_rejects_bad_schema(client, auth_headers):
    create = await client.post(
        "/v1/agents",
        headers=auth_headers,
        json={"name": "A", "system_prompt": "be helpful"},
    )
    assert create.status_code == 201
    agent_id = create.json()["id"]

    bad = await client.patch(
        f"/v1/agents/{agent_id}",
        headers=auth_headers,
        json={"analysis_plan": {"structured_data_schema": {"type": "nope"}}},
    )
    assert bad.status_code == 422
    detail = bad.json()["detail"]
    assert detail["field"] == "analysis_plan"


@pytest.mark.asyncio
async def test_patch_accepts_valid_plan(client, auth_headers):
    create = await client.post(
        "/v1/agents",
        headers=auth_headers,
        json={"name": "B", "system_prompt": "be helpful"},
    )
    agent_id = create.json()["id"]

    ok = await client.patch(
        f"/v1/agents/{agent_id}",
        headers=auth_headers,
        json={
            "analysis_plan": {
                "summary_prompt": "summarize",
                "structured_data_schema": {"type": "object"},
            }
        },
    )
    assert ok.status_code == 200, ok.text
