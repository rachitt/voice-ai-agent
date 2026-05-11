# Soniq Web

React frontend for Soniq.

The web app provides the first product surfaces for building and testing voice
agents: a launch console, a visual flow builder, and a browser-based call test
page that connects to the Soniq API over HTTP and WebSockets.

## Stack

- Vite
- React
- TypeScript
- Tailwind CSS
- React Router
- React Flow
- Zustand
- Recharts
- lucide-react
- Playwright

## Local Development

```bash
pnpm install
pnpm dev
```

The app runs at `http://localhost:5173` by default.

To point the app at a running API, open the browser web-call page and set:

- API base: `http://localhost:8000`
- API key: the key printed by `apps/api/scripts/seed_dev.py`

## Routes

- `/` launch console
- `/builder/:agentId` visual agent builder
- `/builder` redirects to `/builder/demo`
- `/web-call` browser call testing
- `/analytics`, `/numbers`, `/knowledge`, `/tools`, `/settings` placeholder
  product sections

## Testing

```bash
pnpm build
pnpm test:e2e
```

The Playwright suite covers console rendering, builder interactions, graph
editing, validation behavior, API-backed persistence, publish errors, and test
call creation.

## Layout

```text
src/app
  router and shell

src/lib
  API client, websocket call client, utilities

src/pages/console
  launch console panels and fixtures

src/pages/builder
  React Flow canvas, node palette, inspector, store, validation rules

src/pages/web-call
  browser call testing UI
```
