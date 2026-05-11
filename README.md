# voice-ai-agent

End-to-end voice AI platform. Retell/Vapi alt. Built on Deepgram STT + ElevenLabs TTS + Gemini LLM + Telnyx PSTN, React frontend, FastAPI backend.

## Phase 1 (current)

Frontend shells only:
- **Launch Console** (`/`) — deployment checklist, live call simulator, transcript, metrics
- **Agent Builder** (`/builder/:agentId`) — node-graph flow editor

Mock FastAPI backs both with fixtures. No real voice loop, no telephony, no LLM yet.

## Dev

```bash
pnpm --dir apps/web install
pnpm --dir apps/web dev          # http://localhost:5173

# (later)
cd apps/api && uvicorn app.main:app --reload --port 8000
```

## Layout

```
apps/web/    Vite + React + TS + Tailwind v4 + shadcn-style primitives
apps/api/    FastAPI mock (fixtures)
tasks/       lessons.md (append-only mistakes log per CLAUDE.md)
```

## Stack

- FE: Vite, React 18, TS, Tailwind v4, @xyflow/react, zustand, recharts, lucide-react
- BE: FastAPI (mock for now)
- LLM: Gemini (phase 2)
- STT/TTS: Deepgram / ElevenLabs (phase 2)
- Telephony: Telnyx (phase 2)
- DB: Postgres + Redis (phase 2)
