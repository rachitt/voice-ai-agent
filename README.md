# Soniq

Soniq is a full-stack voice AI agent platform built around a simple product idea:
voice agents should be designed, tested, observed, and improved like real software
systems, not treated as black boxes.

The project is an early build-in-public workspace for a Retell/Vapi-style voice
agent platform. It combines a visual agent builder, launch console, browser call
testing, FastAPI backend, realtime websocket transport, telephony integration,
and a streaming STT -> LLM -> TTS pipeline scaffold.

## Why Soniq

Voice agents are becoming practical, but the tooling still tends to optimize for
getting a demo online quickly. Soniq is being designed for the next step: making
agents easier to reason about, inspect, and iterate after real conversations.

Core design goals:

- Make conversation flow explicit through a visual builder.
- Keep the call loop observable through transcripts, events, tools, and metrics.
- Support fast local testing before deploying to phone numbers.
- Treat telephony, tools, knowledge, and analysis as first-class product surfaces.
- Preserve enough control for production business workflows.

## Current Capabilities

This repo already contains the first vertical slice of the platform.

### Web App

- Launch console with deployment checklist, live-call surface, transcript,
  tool-call panel, metrics, safety/compliance status, and launch history.
- Visual agent builder powered by React Flow.
- Builder controls for core conversation blocks: greeting, collect, condition,
  API call, transfer, voicemail, and end call.
- Flow validation rules for connection constraints, branch labels, terminal
  nodes, cycles, and unreachable nodes.
- Browser web-call page for starting a call against an agent, connecting over a
  websocket, and testing in text-only or microphone mode.
- Local API base/key configuration for connecting the web app to a running API.

### API

- FastAPI backend with authenticated REST routes for:
  - agents and published versions
  - tools
  - phone numbers
  - knowledge bases and source ingestion
  - squads
  - web and phone calls
  - call event streams
  - Telnyx webhooks
- SQLAlchemy models and Alembic migrations for orgs, users, API keys, agents,
  versions, tools, numbers, knowledge bases, chunks, squads, calls, call events,
  and webhook outbox rows.
- API-key auth with hashed keys and org-scoped access.
- Server-sent event stream for live call spectators.
- Seed script for local development.

### Realtime Voice Loop

- Browser websocket transport for web calls.
- Telnyx media websocket bridge for PSTN calls.
- Audio conversion between Telnyx μ-law 8 kHz and pipeline PCM16 16 kHz.
- Deepgram streaming STT integration scaffold.
- LiteLLM/Gemini streaming turn generation.
- ElevenLabs TTS streaming scaffold.
- Tool-call dispatch loop with tool results fed back into the model.
- Barge-in handling by cancelling an in-flight agent turn when a final user
  utterance arrives.
- Transcript persistence when calls close.

### Test Coverage

The repo includes API and web tests for:

- auth and API key behavior
- agent CRUD, draft updates, publishing, and versioning
- flow graph validation
- web call creation and websocket token signing
- call event streams and short-lived stream tokens
- event bus fanout
- phone dialing through Telnyx client boundaries
- Telnyx webhook signatures and audio conversion
- pipeline orchestration, tool loops, TTS splitting, and barge-in
- knowledge-base ingestion and chunking
- console, builder, persistence, and publish flows in Playwright

## Architecture

```text
apps/web
  Vite + React + TypeScript
  Tailwind CSS
  React Router
  React Flow
  Zustand
  Recharts
  Playwright e2e tests

apps/api
  FastAPI
  SQLAlchemy + Alembic
  Postgres + pgvector
  Redis
  MinIO-compatible object storage
  Deepgram STT
  LiteLLM/Gemini LLM
  ElevenLabs TTS
  Telnyx PSTN/media streaming
  pytest test suite

assets
  Build-in-public creative assets and social images

tasks
  Project notes and lessons log
```

## Local Development

### Prerequisites

- Node.js and pnpm
- Python 3.11+
- uv
- Docker

### Start infrastructure

```bash
docker compose up -d postgres redis minio
```

### Start the API

```bash
cd apps/api
uv sync
uv run alembic upgrade head
PYTHONPATH=. uv run python scripts/seed_dev.py
PYTHONPATH=. uv run uvicorn app.main:app --reload --port 8000
```

The seed script prints a local API key. Use that key in the web app when testing
authenticated flows.

### Start the web app

```bash
pnpm --dir apps/web install
pnpm --dir apps/web dev
```

The web app runs at `http://localhost:5173` by default.

## Useful Commands

```bash
# API tests
cd apps/api
PYTHONPATH=. uv run pytest

# Web build
pnpm --dir apps/web build

# Web e2e tests
pnpm --dir apps/web test:e2e
```

## Environment

API settings use the `VOICE_` prefix. Important local/prod configuration values:

- `VOICE_DATABASE_URL`
- `VOICE_REDIS_URL`
- `VOICE_S3_ENDPOINT`
- `VOICE_ENABLE_OBJECT_STORE`
- `VOICE_PUBLIC_BASE_URL`
- `VOICE_PUBLIC_WS_BASE_URL`
- `VOICE_TELNYX_API_KEY`
- `VOICE_TELNYX_WEBHOOK_PUBLIC_KEY`
- `VOICE_TELNYX_CONNECTION_ID`
- `VOICE_DEEPGRAM_API_KEY`
- `VOICE_ELEVENLABS_API_KEY`
- `VOICE_GEMINI_API_KEY`
- `VOICE_WEBHOOK_HMAC_SECRET`
- `VOICE_API_KEY_PEPPER`
- `VOICE_CORS_ORIGINS`

## Roadmap

- Harden the browser call experience and make local agent testing smoother.
- Connect the visual builder more deeply to the runtime flow graph.
- Expand tool definitions, tool execution history, and debugging surfaces.
- Improve knowledge-base retrieval and source management.
- Add post-call analysis, scoring, and evaluation workflows.
- Productionize Telnyx call handling, webhook delivery, and deployment docs.
- Add billing, workspace/team flows, and hosted infrastructure when the core
  product loop is stable.

## Build In Public

Soniq is being built in public from day one. The goal is to share not just
features, but the design decisions, tradeoffs, and mistakes behind building a
voice agent platform that people can actually operate.
