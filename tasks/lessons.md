# Lessons

Append-only mistakes log. Keep <300 lines (CLAUDE.md §2). Read at start of every session.

## 2026-05-11

- TS 6 deprecates `baseUrl` in tsconfig. Path aliases work without it via `paths` alone when `moduleResolution: "bundler"`. Don't add `baseUrl` to new Vite scaffolds.
- Tailwind v4 uses `@import "tailwindcss"` + `@theme { --color-* }` block — no `tailwind.config.ts` needed for tokens.
