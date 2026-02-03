#!/usr/bin/env bash
# Create repo and push to GitHub. Set GITHUB_USER and optionally GITHUB_REPO (default: kv-store).
# Usage: ./scripts/git_push.sh
set -e
cd "$(dirname "$0")/.."
GITHUB_USER="${GITHUB_USER:-}"
GITHUB_REPO="${GITHUB_REPO:-kv-store}"
if [ -z "$GITHUB_USER" ]; then
  echo "Set GITHUB_USER (and optionally GITHUB_REPO) then run again."
  echo "Example: GITHUB_USER=myuser ./scripts/git_push.sh"
  exit 1
fi
git init
git add .
git commit -m "Initial commit: KV-Store with WAL, tests, benchmarks, replication" || true
git branch -M main
git remote add origin "https://github.com/${GITHUB_USER}/${GITHUB_REPO}.git" 2>/dev/null || git remote set-url origin "https://github.com/${GITHUB_USER}/${GITHUB_REPO}.git"
echo "Push with: git push -u origin main"
git push -u origin main
