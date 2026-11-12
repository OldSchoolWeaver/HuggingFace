#!/usr/bin/env bash
# Deploy this repo to GitHub and/or push one app folder as the root of its Hugging Face Space.
#
# Usage:
#   ./deploy_space.sh [hf] <app>                       # app folder -> its HF Space (default target)
#   ./deploy_space.sh github                           # whole repo  -> GitHub
#   ./deploy_space.sh all <app>                        # both: GitHub first, then the Space
#   ./deploy_space.sh reqs <app>                       # regenerate <app>/requirements.txt from its uv.lock
#   <app> is one of: shopping_agent, research_agent, financial_researcher_agent
#   (see app_target() below), or "<folder> <hf_user/space>" for anything else.
#
# Examples:
#   ./deploy_space.sh research_agent                   # -> MiguelBayanSoares/Research_Agent
#   ./deploy_space.sh all shopping_agent
#   ./deploy_space.sh research_agent MiguelBayanSoares/Some_Other_Space
#
# Only COMMITTED changes are deployed. The Space must already exist on huggingface.co.
# Apps are uv projects, but Spaces install requirements.txt: before deploying, the script checks that the
# committed requirements.txt matches uv.lock, and stops if not (fix: ./deploy_space.sh reqs <app>, then commit).
# HF:     uses $HF_TOKEN if set, otherwise your git credentials. The Space is force-pushed (it's a build target).
# GitHub: pushes the current branch to $GITHUB_URL with a normal (non-force) push, so history is never overwritten.
#         Uses $GITHUB_TOKEN (a PAT of an account with write access) if set, otherwise your git credentials.
set -euo pipefail

GITHUB_URL="${GITHUB_URL:-https://github.com/OldSchoolWeaver/HuggingFace.git}"

# Folder -> "<folder> <hf_user/space>". Add a line per new app.
# (a case statement, not an associative array: macOS ships bash 3.2, which doesn't have them)
app_target() {
  case "$1" in
    shopping_agent)             echo "shopping_agent MiguelBayanSoares/shopping_list" ;;
    research_agent)             echo "research_agent MiguelBayanSoares/Research_Agent" ;;
    financial_researcher_agent) echo "financial_researcher_agent MiguelBayanSoares/Financial_Researcher" ;;
  esac
}
KNOWN_APPS="shopping_agent research_agent financial_researcher_agent"

usage() { sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

warn_uncommitted() {
  if [[ -n "$(git status --porcelain)" ]]; then
    echo "⚠️  You have uncommitted changes - they will NOT be deployed (commit them first)."
  fi
}

# Sets APP_PATH and SPACE from either a known folder ("research_agent") or "<folder> <space>".
resolve_app() {
  if [[ $# -eq 1 && -n "$(app_target "$1")" ]]; then
    read -r APP_PATH SPACE <<< "$(app_target "$1")"
  elif [[ $# -eq 2 ]]; then
    APP_PATH="$1"; SPACE="$2"
  else
    echo "❌ Unknown app '${1:-}'. Known: $KNOWN_APPS (or pass '<folder> <hf_user/space>')."; exit 1
  fi
}

# Every package in uv.lock (exact versions), without the dev group: what the Space should install.
export_reqs() {
  (cd "$1" && uv export --frozen --no-hashes --no-dev --no-emit-project --no-annotate --no-header -q) | grep -v '^[[:space:]]*$'
}

write_reqs() {
  local app_path="$1"
  [[ -f "$app_path/uv.lock" ]] || { echo "❌ $app_path has no uv.lock."; exit 1; }
  (cd "$app_path" && uv lock -q)   # make sure the lock matches pyproject.toml first
  {
    echo "# Generated from uv.lock by ./deploy_space.sh reqs $app_path - don't edit by hand."
    echo "# Change dependencies with uv add / uv remove in this folder, then run that command again and commit."
    echo "# The Space installs this file: Hugging Face doesn't read pyproject.toml or uv.lock."
    export_reqs "$app_path"
  } > "$app_path/requirements.txt"
  echo "✅ Wrote $app_path/requirements.txt ($(grep -vc '^#' "$app_path/requirements.txt") packages). Commit it before deploying."
}

# Stop the deploy if the COMMITTED requirements.txt doesn't match uv.lock (the Space would install other versions).
check_requirements() {
  local app_path="$1" expected committed
  [[ -f "$app_path/uv.lock" ]] || return 0   # not a uv project: nothing to compare
  if ! command -v uv >/dev/null 2>&1; then
    echo "⚠️  uv isn't installed, so requirements.txt can't be checked against uv.lock."; return 0
  fi
  if ! (cd "$app_path" && uv lock --check -q 2>/dev/null); then
    echo "❌ $app_path/uv.lock is out of date with pyproject.toml. Run: ./deploy_space.sh reqs $app_path, then commit."
    exit 1
  fi
  expected="$(export_reqs "$app_path")"
  committed="$(git show "HEAD:$app_path/requirements.txt" 2>/dev/null | grep -v '^#' | grep -v '^[[:space:]]*$' || true)"
  if [[ "$expected" != "$committed" ]]; then
    echo "❌ The committed $app_path/requirements.txt doesn't match uv.lock."
    echo "   Run: ./deploy_space.sh reqs $app_path, then commit, then deploy again."
    exit 1
  fi
}

deploy_github() {
  local branch
  branch="$(git branch --show-current)"
  [[ -n "$branch" ]] || { echo "❌ Not on a branch (detached HEAD)."; exit 1; }
  local url="$GITHUB_URL"
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    url="https://x-access-token:${GITHUB_TOKEN}@${GITHUB_URL#https://}"
  fi
  echo "→ Pushing '$branch' to GitHub ($GITHUB_URL)"
  git push "$url" "$branch:$branch"
  echo "✅ GitHub updated: ${GITHUB_URL%.git}/tree/$branch"
}

deploy_hf() {
  local app_path="$1" space="$2"
  local branch="space-deploy-$(echo "$app_path" | tr '/' '-')"
  local url

  [[ -d "$app_path" ]] || { echo "❌ Folder '$app_path' not found."; exit 1; }
  check_requirements "$app_path"
  if [[ -n "${HF_TOKEN:-}" ]]; then
    url="https://${space%%/*}:${HF_TOKEN}@huggingface.co/spaces/${space}"
  else
    url="https://huggingface.co/spaces/${space}"
  fi

  echo "→ Pushing '$app_path' as the root of Space $space"
  git branch -D "$branch" >/dev/null 2>&1 || true   # leftover from an interrupted run
  git subtree split --prefix="$app_path" -b "$branch"
  git push --force "$url" "$branch:main"
  git branch -D "$branch" >/dev/null
  echo "✅ Space updated: https://huggingface.co/spaces/$space"
}

[[ $# -ge 1 ]] || usage

case "$1" in
  -h|--help) usage ;;
  github)
    warn_uncommitted
    deploy_github
    ;;
  reqs)
    shift
    [[ $# -eq 1 && -d "$1" ]] || { echo "❌ Usage: ./deploy_space.sh reqs <app folder>"; exit 1; }
    write_reqs "${1%/}"
    ;;
  all)
    shift
    resolve_app "$@"
    warn_uncommitted
    check_requirements "$APP_PATH"   # before GitHub, so a bad requirements.txt isn't pushed either
    deploy_github
    deploy_hf "$APP_PATH" "$SPACE"
    ;;
  hf)
    shift
    resolve_app "$@"
    warn_uncommitted
    deploy_hf "$APP_PATH" "$SPACE"
    ;;
  *)
    resolve_app "$@"
    warn_uncommitted
    deploy_hf "$APP_PATH" "$SPACE"
    ;;
esac
