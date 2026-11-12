#!/usr/bin/env bash
# Rebuild the virtual environment of every uv project in this repo: delete its .venv, then `uv sync`.
#
# Usage:
#   ./sync_envs.sh                  # every uv project (each folder with pyproject.toml + uv.lock)
#   ./sync_envs.sh research_agent   # only the folders you name
#   ./sync_envs.sh --dry-run        # list what it would rebuild, change nothing
#
# Use it after changing Python (e.g. a new .python-version) or when a .venv is broken.
# `uv sync --locked` installs exactly what uv.lock says and never changes the lock; if a lock is out of date with its
# pyproject.toml, that project fails with a message (fix: `uv lock` in that folder). Generated folders are skipped:
# engineering_team_agent/sandbox/ (the crew rebuilds it on every run), .venv/, output/, runs/.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

DRY_RUN=false
SELECTED=()
for arg in "$@"; do
  case "$arg" in
    -n|--dry-run) DRY_RUN=true ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) SELECTED+=("${arg%/}") ;;
  esac
done

command -v uv >/dev/null 2>&1 || { echo "❌ uv isn't installed (brew install uv)."; exit 1; }

# Every folder with both pyproject.toml and uv.lock, outside generated folders.
projects=()
while IFS= read -r lock; do
  projects+=("$(dirname "${lock#./}")")
done < <(find . \( -name .venv -o -name .git -o -name sandbox -o -name node_modules -o -name output -o -name runs \) -prune \
              -o -name uv.lock -print | sort)

if [[ ${#SELECTED[@]} -gt 0 ]]; then
  chosen=()
  for s in "${SELECTED[@]}"; do
    found=false
    for p in "${projects[@]}"; do [[ "$p" == "$s" ]] && { chosen+=("$p"); found=true; }; done
    $found || { echo "❌ '$s' isn't a uv project here. Known: ${projects[*]}"; exit 1; }
  done
  projects=("${chosen[@]}")
fi

ok=(); failed=()
for p in "${projects[@]}"; do
  [[ -f "$p/pyproject.toml" ]] || continue
  echo "━━ $p"
  if $DRY_RUN; then
    echo "   would delete $p/.venv and run: uv sync --locked"; continue
  fi
  if [[ -d "$p/.venv" ]]; then
    rm -rf "${ROOT:?}/$p/.venv"   # always the .venv inside a project folder of this repo
  fi
  if (cd "$p" && uv sync --locked); then
    ok+=("$p ($("$p/.venv/bin/python" --version 2>&1))")
  else
    failed+=("$p")
  fi
done

echo
echo "━━ Summary"
for p in ${ok[@]+"${ok[@]}"}; do echo "✅ $p"; done
for p in ${failed[@]+"${failed[@]}"}; do echo "❌ $p"; done
[[ ${#failed[@]} -eq 0 ]]
