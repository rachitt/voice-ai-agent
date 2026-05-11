# Voice 2.0 API

FastAPI backend. Phase 2 scaffold — REST CRUD for agents/tools/phone-numbers/knowledge-bases/squads/calls + Telnyx webhook stub + webhook outbox dispatcher.

## Dev

```bash
# from repo root
docker compose -f docker-compose.yml up -d postgres redis

# from apps/api
cp .env.example .env
uv sync
uv run alembic upgrade head
PYTHONPATH=. uv run python scripts/seed_dev.py   # prints API key
PYTHONPATH=. uv run uvicorn app.main:app --reload --port 8088
```

Smoke:
```bash
KEY=sk_live_...
curl -s http://localhost:8088/healthz
curl -s -X POST http://localhost:8088/v1/agents \
  -H "Authorization: Bearer $KEY" -H "content-type: application/json" \
  -d '{"name":"Demo","first_message":"Hi","system_prompt":"helpful"}'
```

## Layout

```
app/
  core/        config, logging, ids, security, auth
  db/          base, session, models
  routers/     agents, tools, phone_numbers, knowledge_bases, squads, calls, webhooks
  schemas/     pydantic IO models
  telephony/   Telnyx client
  webhooks/    outbox dispatcher
alembic/       migrations
scripts/       seed_dev.py
tests/         pytest suite (TBD)
```

## Out of scope this commit

Pipeline orchestrator (STT/LLM/TTS), LiveKit room mgmt, Telnyx webhook signature verify, KB ingestion pipeline, post-call analysis runner, S3 bucket bootstrap, mobile SDKs.
