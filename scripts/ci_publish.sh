#!/usr/bin/env bash
# Upload changed PDFs to R2, then commit generated paths only.
# Pushes to GITHUB_REF_NAME (the branch this workflow checked out).
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

mapfile -t pdfs < <(git ls-files -m -o --exclude-standard -- 'docs/assets/pdfs')

if ((${#pdfs[@]})); then
  if [[ -z "${CLOUDFLARE_API_TOKEN:-}" || -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]]; then
    echo "PDFs changed but CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID are unset." >&2
    exit 1
  fi
  for file in "${pdfs[@]}"; do
    key="${file#docs/assets/pdfs/}"
    echo "R2 put nanodocs-pdfs/${key}"
    npx --yes wrangler@4 r2 object put "nanodocs-pdfs/${key}" \
      --file="$file" \
      --content-type=application/pdf \
      --remote
  done
else
  echo "No PDF changes; skipping R2."
fi

git add -- .sync-state.json docs/

if git diff --cached --quiet; then
  echo "unchanged"
  exit 0
fi

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

msg="Sync Google Docs"
if [[ -n "${SYNC_ONLY:-}" ]]; then
  msg="Sync Google Docs (${SYNC_ONLY})"
fi

git commit -m "$msg"
git push origin "HEAD:${GITHUB_REF_NAME:?}"
