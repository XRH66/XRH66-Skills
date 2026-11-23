#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)

for f in "$repo_dir"/scripts/*.sh; do
  bash -n "$f"
done

python_bin=${PYTHON:-}
if [[ -z "$python_bin" ]]; then
  if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys' >/dev/null 2>&1; then
    python_bin=python3
  elif command -v python >/dev/null 2>&1; then
    python_bin=python
  else
    echo "error: python3 or python is required" >&2
    exit 1
  fi
fi

"$python_bin" "$repo_dir/scripts/validate_skill.py" "$repo_dir"

echo "validation: ok"
