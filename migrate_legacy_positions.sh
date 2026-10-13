#!/usr/bin/env bash
# Move the vehicle positions archive from JSON day files to CSV, one day at a
# time, whenever the publishing job runs.
#
#   migrate_legacy_positions.sh [GTFS_BUNDLE]
#
# Until 2026-10-13 each day was septapositions_<DAY>.json. Every run, this
# folds each such file left on the release into that day's CSV (joining rows
# the CSV already has, so a day split across both formats ends up whole),
# uploads the CSV, and only then deletes the JSON. With GTFS_BUNDLE, the rows
# it converts are named from it.
#
# Once no JSON day files remain it does nothing but one listing, so it can stay
# until someone removes it. A failure part way leaves the JSON in place for the
# next run to retry: nothing is deleted until its CSV is uploaded and holds at
# least as many rows.
#
# Needs GH_TOKEN and GITHUB_REPOSITORY, as set in a GitHub Actions job.

set -euo pipefail

RELEASE=vehicle-positions
PREFIX=septapositions
BUNDLE="${1:-}"

if ! NAMES="$(gh release view "${RELEASE}" --repo "${GITHUB_REPOSITORY}" \
    --json assets --jq '.assets[].name' 2>/dev/null)"; then
  echo "No ${RELEASE} release; nothing to migrate"
  exit 0
fi

mapfile -t LEGACY < <(
  grep -E "^${PREFIX}_[0-9]{4}-[0-9]{2}-[0-9]{2}\.json$" <<< "${NAMES}" || true)
if [ "${#LEGACY[@]}" -eq 0 ]; then
  echo "No JSON day files left to migrate"
  exit 0
fi

NAME_ARGS=()
if [ -n "${BUNDLE}" ] && [ -f "${BUNDLE}" ]; then
  NAME_ARGS=(--gtfs-bundle "${BUNDLE}")
else
  echo "::notice::Migrating without stop, trip and direction names"
fi

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

for json in "${LEGACY[@]}"; do
  day="${json#"${PREFIX}_"}"
  day="${day%.json}"
  csv="${PREFIX}_${day}.csv"
  mkdir -p "${WORK}/${day}/in" "${WORK}/${day}/out"

  gh release download "${RELEASE}" --repo "${GITHUB_REPOSITORY}" \
    --pattern "${json}" --dir "${WORK}/${day}/in"
  DAY_ARGS=()
  if grep -Fxq "${csv}" <<< "${NAMES}"; then
    gh release download "${RELEASE}" --repo "${GITHUB_REPOSITORY}" \
      --pattern "${csv}" --dir "${WORK}/${day}/in"
    DAY_ARGS=(--day "${WORK}/${day}/in/${csv}")
  fi

  python merge_vehicle_positions.py \
    --legacy-json "${WORK}/${day}/in/${json}" "${NAME_ARGS[@]}" \
    "${DAY_ARGS[@]}" --output "${WORK}/${day}/out/${csv}"

  # The CSV must hold every row the JSON did before the JSON may go.
  python - "${WORK}/${day}/in/${json}" "${WORK}/${day}/out/${csv}" <<'EOF'
import csv
import json
import sys

legacy, converted = sys.argv[1:]
with open(legacy, encoding="utf-8") as handle:
    expected = sum(len(s["vehicles"]) for s in json.load(handle)["samples"])
with open(converted, encoding="utf-8", newline="") as handle:
    found = sum(1 for _ in csv.DictReader(handle))
if found < expected:
    sys.exit(f"::error::{converted} has {found} rows, fewer than the "
             f"{expected} in {legacy}")
print(f"{converted}: {found} rows, covering the {expected} from {legacy}")
EOF

  gh release upload "${RELEASE}" --clobber --repo "${GITHUB_REPOSITORY}" \
    "${WORK}/${day}/out/${csv}"
  gh release delete-asset "${RELEASE}" "${json}" \
    --repo "${GITHUB_REPOSITORY}" --yes
  echo "Migrated ${json} to ${csv}"
done
