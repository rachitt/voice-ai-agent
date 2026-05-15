/// <reference types="vite/client" />

// Injected by vite.config.ts via `define`. In dev, points at the API host
// (typically http://127.0.0.1:8000) so WebSocket connections bypass the
// vite proxy. In prod, same origin as the page.
declare const __VITE_API_ORIGIN__: string
