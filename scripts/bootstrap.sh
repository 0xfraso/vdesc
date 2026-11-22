#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
repo="$(pwd)"

recreate() {
  echo "bootstrap: recreating .venv ($1)"
  rm -rf .venv
  uv venv .venv --python 3.12
  uv pip install -e ".[dev,youtube]" --python .venv/bin/python
}

reason=""
if [[ ! -x .venv/bin/python ]]; then
  reason="venv missing"
else
  for f in .venv/bin/*; do
    [[ -f "$f" ]] || continue
    IFS= read -r first < "$f" || true
    [[ "$first" == '#!'* ]] || continue
    read -r -a interp <<< "${first:2}"
    ((${#interp[@]})) || continue
    [[ -x "${interp[0]}" ]] || { reason="stale shebang in $f"; break; }
  done
fi
if [[ -z "$reason" ]]; then
  for pth in .venv/lib/python*/site-packages/*.pth; do
    [[ -f "$pth" ]] || continue
    while IFS= read -r line || [[ -n "$line" ]]; do
      line="${line%%#*}"
      [[ "$line" == /* ]] || continue
      if [[ "$line" != "$repo"/* ]]; then
        reason="editable path outside repo in $pth"
        break 2
      fi
    done < "$pth"
  done
fi

if [[ -n "$reason" ]]; then
  recreate "$reason"
else
  echo "bootstrap: venv ok"
  uv pip install -e ".[dev,youtube]" --python .venv/bin/python >/dev/null
fi
