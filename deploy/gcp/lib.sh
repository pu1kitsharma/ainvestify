#!/usr/bin/env bash
# Shared helper. DEFAULT IS DRY RUN: `run` prints the command. Only APPLY=1 executes.
# No script in this folder has ever been executed by the authors.
set -euo pipefail
APPLY="${APPLY:-0}"
run() {
  if [[ "$APPLY" == "1" ]]; then
    echo "+ $*" >&2; "$@"
  else
    printf '[dry-run] would run:'; printf ' %q' "$@"; printf '\n'
  fi
}
require_var() { [[ -n "${!1:-}" ]] || { echo "Set $1 (see env.example)" >&2; exit 2; }; }
if [[ "$APPLY" == "1" ]]; then
  [[ "${I_HAVE_AN_APPROVED_GPU_RUN_PLAN:-}" == "yes" ]] || { echo "APPLY=1 needs I_HAVE_AN_APPROVED_GPU_RUN_PLAN=yes (deployment/GPU_RUN_PLAN_TEMPLATE.md)" >&2; exit 3; }
fi
