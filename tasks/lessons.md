# Lessons

Append-only mistakes log. Keep <300 lines (CLAUDE.md §2). Read at start of every session.

## 2026-05-11

- TS 6 deprecates `baseUrl` in tsconfig. Path aliases work without it via `paths` alone when `moduleResolution: "bundler"`. Don't add `baseUrl` to new Vite scaffolds.
- Tailwind v4 uses `@import "tailwindcss"` + `@theme { --color-* }` block — no `tailwind.config.ts` needed for tokens.
- React Flow v12 needs explicit generic: `<ReactFlow<StepNode> ... />`, else `onNodesChange` widens to `Node` and breaks the store handler.
- React StrictMode double-mounts effects. Streaming-from-index patterns with a local `let i = 0` produce duplicate or out-of-bounds reads. Compute next index inside `setState` updater from existing array length + dedupe by id.
- Vite default port 5173 is shared across worktrees on this machine — another project's SvelteKit dev server squats on it. Vite auto-falls-back to 5174. Either accept that or pin a unique port in `vite.config.ts`.
- Always verify UI in browser before claiming done — build-clean ≠ runtime-clean. The first console render had an uncaught TypeError despite `pnpm build` passing.
- structlog reserves the kwarg name `event` — passing `event=...` to `log.info(...)` raises `got multiple values for argument 'event'`. Use `event_type=` or any other key.
- Async SQLAlchemy: after `session.expire_all()`, accessing `obj.id` triggers a sync lazy-load that errors with `MissingGreenlet`. Capture primary keys into local vars (`row_id = row.id`) before the expire.
- Adding a child row that FKs back to a parent in the same commit needs an `await db.flush()` between `db.add(parent)` and `db.add(child)`, otherwise the child sees `parent.id = None` and Postgres rejects with `NotNullViolation`.
- `audioop-lts` PyPI package installs under the module name `audioop`, so `import audioop` works on 3.11/3.12 (stdlib) and 3.13+ (LTS shim) with no branching. Declare it as `audioop-lts>=0.2.2; python_version>='3.13'` and silence the 3.11 deprecation via `warnings.filterwarnings` around the import.
- Vite 8 with Rolldown bundler — `build.rolldownOptions.output.manualChunks` only accepts a **function** `(id) => 'name'`, not the Rollup-style `{name: [pkgs]}` object form. The latter type-errors at build.
- Pipeline `on_turn_end` callbacks must NOT directly `await pipe.close()` — the close path awaits `cancel_current_turn`, which would self-cancel the very turn task that's running the callback (deadlock → asyncio TimeoutError in tests). Schedule the close via `asyncio.create_task(pipe.close())` so it runs on the next loop tick after the turn task finishes.
- Flow-graph `condition` nodes classify against the **already-completed** turn — entering a condition node must run the classifier synchronously and route immediately. Waiting for a second user turn would never fire because the agent hasn't said anything to prompt one.
