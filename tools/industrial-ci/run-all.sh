#!/usr/bin/env bash
# Run the full build.yml matrix locally (same order as GitHub Actions).
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_ONE="$DIR/run-one.sh"

MATRIX=(
  "humble gcc"
  "humble clang"
  "jazzy gcc"
  "jazzy clang"
  "jazzy gcc-asan"
  "jazzy gcc-tsan"
)

failed=()
for cell in "${MATRIX[@]}"; do
  distro="${cell%% *}"
  test_type="${cell#* }"
  if ! "$RUN_ONE" "$distro" "$test_type"; then
    failed+=("$distro,$test_type")
  fi
done

if ((${#failed[@]} > 0)); then
  echo "failed matrix cells:" >&2
  printf '  %s\n' "${failed[@]}" >&2
  exit 1
fi

echo "all ${#MATRIX[@]} matrix cells passed"
