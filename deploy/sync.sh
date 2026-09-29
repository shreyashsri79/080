#!/usr/bin/env bash
# Push local pipeline outputs to the Modal Volume behind https://<workspace>--regimerain.modal.run
#   deploy/sync.sh                 all runs/, reports/, models/ that exist locally
#   deploy/sync.sh runs/<run_id>   one item
# The site picks them up within 30 s; no redeploy needed. Re-uploading a run replaces it.
set -euo pipefail
cd "$(dirname "$0")/.."
VOL=regimerain-data
items=("$@")
if [ ${#items[@]} -eq 0 ]; then
  for d in runs reports models; do
    [ -d "$d" ] && for x in "$d"/*/; do [ -d "$x" ] && items+=("${x%/}"); done
  done
fi
[ ${#items[@]} -eq 0 ] && { echo "nothing to upload (no runs/, reports/ or models/)"; exit 1; }
for x in "${items[@]}"; do
  case "$x" in *.partial|*/.tmp-*) continue;; esac
  echo "-> /$x"
  modal volume put --force "$VOL" "$x" "/$x"
done
modal volume ls "$VOL" /runs
