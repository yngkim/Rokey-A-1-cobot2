#!/usr/bin/env bash
# GitHub push (히스토리가 달라 force push 필요)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

if ! git remote get-url origin >/dev/null 2>&1; then
  git remote add origin https://github.com/yngkim/Rokey-A-1-cobot2.git
fi

echo "[push] author: $(git config user.name) <$(git config user.email)>"
echo "[push] commits to upload:"
git log --oneline origin/main..HEAD 2>/dev/null || git log --oneline -3

git push --force-with-lease origin main
echo "[push] done: https://github.com/yngkim/Rokey-A-1-cobot2"
