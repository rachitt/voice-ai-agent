# Soniq API

FastAPI backend for Soniq, the voice AI agent platform.

The API owns authenticated platform state, agent versioning, flow graph
validation, calls, realtime call streams, knowledge-base ingestion, telephony
handoff, and the STT -> LLM -> TTS conversation pipeline.

## Local Development

From the repo root, start local services:

```bash
docker compose up -d postgres redis minio
```

Then start the API:

```bash
cd apps/api
uv sync
uv run alembic upgrade head
PYTHONPATH=. uv run python scripts/seed_dev.py
PYTHONPATH=. uv run uvicorn app.main:app --reload --port 8000
```

The seed script prints a development API key. Pass it as:

```bash
Authorization: Bearer <api-key>
```

## Main Surfaces

- `GET /healthz` health check
- `/v1/agents` agent CRUD, draft updates, publish/versioning
- `/v1/tools` tool definitions
- `/v1/phone-numbers` number assignment
- `/v1/knowledge-bases` KBs, sources, ingestion, and chunks
- `/v1/squads` multi-agent squad graph
- `/v1/calls/web` browser call creation
- `/v1/calls/phone` outbound Telnyx call creation
- `/v1/calls/{call_id}/ws` browser realtime websocket
- `/v1/calls/{call_id}/stream` server-sent call event stream
- `/v1/telephony/telnyx/media` Telnyx media websocket bridge
- `/v1/webhooks/telnyx` Telnyx webhook endpoint

## Environment

Settings are read from `.env` with the `VOICE_` prefix.

Common values:

- `VOICE_DATABASE_URL`
- `VOICE_REDIS_URL`
- `VOICE_PUBLIC_BASE_URL`
- `VOICE_PUBLIC_WS_BASE_URL`
- `VOICE_TELNYX_API_KEY`
- `VOICE_TELNYX_WEBHOOK_PUBLIC_KEY`
- `VOICE_TELNYX_CONNECTION_ID`
- `VOICE_DEEPGRAM_API_KEY`
- `VOICE_ELEVENLABS_API_KEY`
- `VOICE_GEMINI_API_KEY`
- `VOICE_API_KEY_PEPPER`
- `VOICE_WEBHOOK_HMAC_SECRET`

## Tests

```bash
cd apps/api
PYTHONPATH=. uv run pytest
```

The suite covers auth, agent publishing, flow validation, calls, streams,
Telnyx boundaries, KB ingestion, event fanout, and pipeline orchestration.

## Layout

```text
app/
  analysis/    post-call analysis scaffolding
  core/        config, logging, ids, security, auth
  db/          SQLAlchemy base, session, models
  kb/          loaders, chunking, vector-store boundaries
  pipeline/    event bus, STT, LLM, TTS, orchestrator, web sessions
  routers/     REST and websocket route modules
  schemas/     Pydantic request/response models
  telephony/   Telnyx client, signatures, audio conversion
  tools/       built-in tool registry
  webhooks/    dispatch/outbox plumbing
alembic/       migrations
scripts/       local seed utilities
tests/         pytest suite
```
