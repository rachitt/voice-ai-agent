"""Validate `analysis_plan` payloads.

The `analysis_plan` field is JSONB on `agent_versions`. It holds three
keys today: `summary_prompt`, `success_prompt`, `structured_data_schema`.
The schema field must be a valid JSON Schema — bad shapes get rejected
here so they don't blow up the post-call analyzer at runtime.
"""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator, SchemaError


def validate_analysis_plan(plan: dict[str, Any] | None) -> list[str]:
    """Return list of error strings (empty if valid)."""
    if plan is None:
        return []
    if not isinstance(plan, dict):
        return ["analysis_plan must be an object"]

    errors: list[str] = []

    summary = plan.get("summary_prompt")
    if summary is not None and not isinstance(summary, str):
        errors.append("summary_prompt must be a string")

    success = plan.get("success_prompt")
    if success is not None and not isinstance(success, str):
        errors.append("success_prompt must be a string")

    schema = plan.get("structured_data_schema")
    if schema is not None:
        if not isinstance(schema, dict):
            errors.append("structured_data_schema must be an object")
        else:
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError as exc:
                errors.append(f"structured_data_schema invalid: {exc.message}")

    return errors
