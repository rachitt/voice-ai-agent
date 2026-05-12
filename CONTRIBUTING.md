# Contributing

## One-time setup

```bash
scripts/install-hooks.sh    # local pre-push gate
cd apps/api && uv sync --all-extras
cd apps/web && pnpm install
```

## CI gates

Every PR runs `api` + `web` jobs in `.github/workflows/ci.yml`. The
`required` aggregate job at the bottom fails if either side fails — pin
that as the only required check in **Repo Settings → Branches →
Branch protection rule for `main`**.

### Branch protection checklist

In GitHub repo settings:

1. **Branches → Add rule** for `main` (and any release branches).
2. Tick **Require a pull request before merging**.
3. Tick **Require status checks to pass before merging** and select
   the `Required checks` job.
4. Tick **Require branches to be up to date before merging**.
5. Tick **Do not allow bypassing the above settings** (so admins can't
   force-push around the gate).

Without this configuration, GitHub will still run CI but won't refuse a
push or merge when checks fail.

### Local pre-push

`scripts/install-hooks.sh` registers `.githooks/pre-push`, which mirrors
the required CI checks (ruff, pytest, tsc, build). Bypass once with
`git push --no-verify` only for WIP branches that won't target `main`.

## What CI enforces today

| Check | Hard gate? | Notes |
| --- | --- | --- |
| `ruff check` | ✓ | API lint |
| `ruff format --check` | ✓ | API formatting |
| `alembic upgrade head` | ✓ | Migrations must apply |
| `alembic check` | ✓ | No drift permitted |
| `mypy` | ✗ | Types tightening incrementally |
| `pytest -n auto` | ✓ | Parallel test run |
| `--cov-fail-under=90` | ✓ | API coverage gate. Raise as coverage grows |
| `pip-audit` | ✗ | Surfacing CVEs; non-blocking |
| `eslint` | ✓ | React 19 set-state-in-effect surfacing pattern bugs |
| `tsc -b` | ✓ | Web type check |
| `pnpm test` (vitest) | ✓ | Web unit tests |
| `pnpm build` | ✓ | Web build |
| Chart bundle ≤ 600 KB | ✓ | Bundle-size guard |
| `playwright test` | ✓ | E2E |
| `pnpm audit --audit-level=high` | ✗ | Non-blocking |

## Test bar

The current snapshot (run via `pytest` / `pnpm test` / `pnpm exec
playwright test`):

- **Backend:** ~385 pytest cases, 93% line coverage. New behaviour
  expects a test in the same PR — pick the closest existing
  `tests/test_*` file and follow its style. Coverage is enforced at
  90% by `--cov-fail-under` in CI.
- **Web unit:** ~17 vitest cases under `src/**/*.test.tsx?`. Pure
  helpers (lib/, components/) should ship with a vitest spec;
  jsdom + `@testing-library/react` are wired up in
  `vitest.config.ts`.
- **Web E2E:** ~53 playwright cases under `apps/web/e2e/`. Reserve
  these for user-facing flows that can't be unit-tested cleanly.

When raising `--cov-fail-under`, never lower it. Bump only after the
suite has stayed above the new floor for several CI runs.

## How to raise a soft gate to hard

1. Fix the underlying violation across the repo.
2. Remove `continue-on-error: true` from the relevant CI step.
3. Re-run CI on a sacrificial PR to confirm.
