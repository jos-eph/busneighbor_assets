#!/usr/bin/env bash
# Fold one snapshot into its UTC day's file on a rolling release, then delete
# day files older than the retention window.
#
#   publish_day_file.sh RELEASE PREFIX MERGE_SCRIPT SNAPSHOT DAY KEEP_DAYS NOTES
#
# The day file is <PREFIX>_<DAY>.json. It is read, merged by MERGE_SCRIPT
# (--snapshot, optional --day, --output) and rewritten, so callers must not
# run two of these against the same release at once.
#
# Every lookup fails the script on error. A failed download is never taken to
# mean "no file yet": that would restart the day from this one snapshot and
# silently drop everything recorded before it.
#
# Needs GH_TOKEN and GITHUB_REPOSITORY, as set in a GitHub Actions job.

set -euo pipefail

if [ "$#" -ne 7 ]; then
  echo "usage: $0 RELEASE PREFIX MERGE_SCRIPT SNAPSHOT DAY KEEP_DAYS NOTES" >&2
  exit 2
fi
RELEASE="$1" PREFIX="$2" MERGE="$3" SNAPSHOT="$4" DAY="$5" KEEP_DAYS="$6" NOTES="$7"

if ! printf '%s' "${DAY}" | grep -Eq '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'; then
  echo "::error::Snapshot date must be YYYY-MM-DD, got '${DAY}'" >&2
  exit 1
fi

if ! gh release view "${RELEASE}" --repo "${GITHUB_REPOSITORY}" >/dev/null 2>&1; then
  # If the view failed for some other reason, create fails on the existing tag
  # and stops the script, which is the right outcome.
  gh release create "${RELEASE}" --repo "${GITHUB_REPOSITORY}" \
    --title "${RELEASE}" --notes "${NOTES}"
fi

ASSET="${PREFIX}_${DAY}.json"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

# Captured first: piping into grep -q under pipefail can SIGPIPE gh and read
# as "not found".
NAMES="$(gh release view "${RELEASE}" --repo "${GITHUB_REPOSITORY}" \
  --json assets --jq '.assets[].name')"
DAY_ARGS=()
if grep -Fxq "${ASSET}" <<< "${NAMES}"; then
  gh release download "${RELEASE}" --repo "${GITHUB_REPOSITORY}" \
    --pattern "${ASSET}" --dir "${WORK}/prev"
  DAY_ARGS=(--day "${WORK}/prev/${ASSET}")
else
  echo "::notice::Starting ${ASSET}"
fi

mkdir -p "${WORK}/out"
python "${MERGE}" --snapshot "${SNAPSHOT}" "${DAY_ARGS[@]}" \
  --output "${WORK}/out/${ASSET}"
gh release upload "${RELEASE}" --clobber --repo "${GITHUB_REPOSITORY}" \
  "${WORK}/out/${ASSET}"
echo "Published ${ASSET}"

# Keeps DAY and the KEEP_DAYS - 1 days before it.
CUTOFF="$(date -u -d "${DAY} -$((KEEP_DAYS - 1)) days" +%F)"
mapfile -t ASSETS < <(gh release view "${RELEASE}" \
  --repo "${GITHUB_REPOSITORY}" --json assets --jq '.assets[].name')
for asset in "${ASSETS[@]}"; do
  [[ "${asset}" =~ ^${PREFIX}_([0-9]{4}-[0-9]{2}-[0-9]{2})\.json$ ]] || continue
  # ISO dates compare correctly as strings.
  if [[ "${BASH_REMATCH[1]}" < "${CUTOFF}" ]]; then
    echo "Deleting ${asset}"
    gh release delete-asset "${RELEASE}" "${asset}" \
      --repo "${GITHUB_REPOSITORY}" --yes
  fi
done
