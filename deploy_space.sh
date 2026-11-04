#!/usr/bin/env bash
# Deploy this repo to GitHub and/or push one unit folder as the root of a Hugging Face Space.
#
# Usage:
#   ./deploy_space.sh [hf] <unit_path> <hf_user/space_name>   # unit folder -> HF Space (default target)
#   ./deploy_space.sh github                                  # whole repo  -> GitHub
#   ./deploy_space.sh all <unit_path> <hf_user/space_name>    # both: GitHub first, then the Space
#
# Examples:
#   ./deploy_space.sh unit1/agent_shopping_list MiguelBayanSoares/shopping_list
#   ./deploy_space.sh github
#   ./deploy_space.sh all unit1/agent_shopping_list MiguelBayanSoares/shopping_list
#
# Only COMMITTED changes are deployed.
# HF:     uses $HF_TOKEN if set, otherwise your git credentials. The Space is force-pushed (it's a build target).
# GitHub: pushes the current branch to $GITHUB_URL with a normal (non-force) push, so history is never overwritten.
#         Uses $GITHUB_TOKEN (a PAT of an account with write access) if set, otherwise your git credentials.
set -euo pipefail

GITHUB_URL="${GITHUB_URL:-https://github.com/OldSchoolWeaver/HuggingFace.git}"

usage() { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

warn_uncommitted() {
  if [[ -n "$(git status --porcelain)" ]]; then
    echo "⚠️  You have uncommitted changes - they will NOT be deployed (commit them first)."
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
  local unit_path="${1:?unit path, e.g. unit1/agent_shopping_list}"
  local space="${2:?space id, e.g. MiguelBayanSoares/shopping_list}"
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
    [[ $# -eq 2 ]] || usage
    warn_uncommitted
    deploy_github
    deploy_hf "$1" "$2"
    ;;
  hf)
    shift
    [[ $# -eq 2 ]] || usage
    warn_uncommitted
    deploy_hf "$1" "$2"
    ;;
  *)  # backwards compatible: ./deploy_space.sh <unit_path> <space>
    [[ $# -eq 2 ]] || usage
    warn_uncommitted
    deploy_hf "$1" "$2"
    ;;
esac
