#!/usr/bin/env bash
# Point git at the in-repo hooks so every contributor gets the pre-push gate.
# Run once after cloning: `scripts/install-hooks.sh`
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

git config core.hooksPath .githooks
chmod +x .githooks/pre-push

echo "installed: core.hooksPath = .githooks"
echo "to bypass once (WIP branches): git push --no-verify"
