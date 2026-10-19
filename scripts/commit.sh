#!/usr/bin/env bash
# ⚒ NIXFORGE · commit state back to git, signed — forged by Swanix 🐸
set -e
git config user.name "nixforge[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add -A
git diff --cached --quiet && { echo "🐸 nothing to save"; exit 0; }
git -c commit.gpgsign=false commit -q -m "$1" -m "Forged-by: Swanix <nixforge>"
for i in 1 2 3 4 5; do
  git pull -q --rebase origin main && git push -q origin HEAD:main && exit 0
  sleep $((i * 3))
done
echo "💥 could not push state"; exit 1
