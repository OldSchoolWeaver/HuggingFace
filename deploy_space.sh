#!/usr/bin/env bash
# Deploy this repo to GitHub and/or push one unit folder as the root of a Hugging Face Space.
#
# Usage:
#   ./deploy_space.sh [hf] <unit>                      # unit folder -> its HF Space (default target)
#   ./deploy_space.sh github                           # whole repo  -> GitHub
#   ./deploy_space.sh all <unit>                       # both: GitHub first, then the Space
#   <unit> is a short name from unit_target() below (unit1, unit2, unit3), or "<folder> <hf_user/space>" for anything else.
#
# Examples:
#   ./deploy_space.sh unit2                            # research agents -> MiguelBayanSoares/Research_Agent
#   ./deploy_space.sh all unit1
#   ./deploy_space.sh unit2/research_agent MiguelBayanSoares/Some_Other_Space
#
# Only COMMITTED changes are deployed. The Space must already exist on huggingface.co.
# HF:     uses $HF_TOKEN if set, otherwise your git credentials. The Space is force-pushed (it's a build target).
# GitHub: pushes the current branch to $GITHUB_URL with a normal (non-force) push, so history is never overwritten.
#         Uses $GITHUB_TOKEN (a PAT of an account with write access) if set, otherwise your git credentials.
set -euo pipefail

GITHUB_URL="${GITHUB_URL:-https://github.com/OldSchoolWeaver/HuggingFace.git}"

# Short name -> "<folder> <hf_user/space>". Add a line per new unit.
# (a case statement, not an associative array: macOS ships bash 3.2, which doesn't have them)
unit_target() {
  case "$1" in
    unit1) echo "unit1/agent_shopping_list MiguelBayanSoares/shopping_list" ;;
    unit2) echo "unit2/research_agent MiguelBayanSoares/Research_Agent" ;;
    unit3) echo "unit3 MiguelBayanSoares/Financial_Researcher" ;;
  esac
}
KNOWN_UNITS="unit1 unit2 unit3"

usage() { sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

warn_uncommitted() {
  if [[ -n "$(git status --porcelain)" ]]; then
    echo "⚠️  You have uncommitted changes - they will NOT be deployed (commit them first)."
  fi
}

# Sets UNIT_PATH and SPACE from either a short name ("unit2") or "<folder> <space>".
resolve_unit() {
  if [[ $# -eq 1 && -n "$(unit_target "$1")" ]]; then
    read -r UNIT_PATH SPACE <<< "$(unit_target "$1")"
  elif [[ $# -eq 2 ]]; then
    UNIT_PATH="$1"; SPACE="$2"
  else
    echo "❌ Unknown unit '${1:-}'. Known: $KNOWN_UNITS (or pass '<folder> <hf_user/space>')."; exit 1
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
  local unit_path="$1" space="$2"
  local branch="space-deploy-$(echo "$unit_path" | tr '/' '-')"
  local url

  [[ -d "$unit_path" ]] || { echo "❌ Folder '$unit_path' not found."; exit 1; }
  if [[ -n "${HF_TOKEN:-}" ]]; then
    url="https://${space%%/*}:${HF_TOKEN}@huggingface.co/spaces/${space}"
  else
    url="https://huggingface.co/spaces/${space}"
  fi

  echo "→ Pushing '$unit_path' as the root of Space $space"
  git branch -D "$branch" >/dev/null 2>&1 || true   # leftover from an interrupted run
  git subtree split --prefix="$unit_path" -b "$branch"
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
  all)
    shift
    resolve_unit "$@"
    warn_uncommitted
    deploy_github
    deploy_hf "$UNIT_PATH" "$SPACE"
    ;;
  hf)
    shift
    resolve_unit "$@"
    warn_uncommitted
    deploy_hf "$UNIT_PATH" "$SPACE"
    ;;
  *)
    resolve_unit "$@"
    warn_uncommitted
    deploy_hf "$UNIT_PATH" "$SPACE"
    ;;
esac
