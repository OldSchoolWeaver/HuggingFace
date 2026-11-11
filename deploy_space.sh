#!/usr/bin/env bash
# Deploy this repo to GitHub and/or push one app folder as the root of its Hugging Face Space.
#
# Usage:
#   ./deploy_space.sh [hf] <app>                       # app folder -> its HF Space (default target)
#   ./deploy_space.sh github                           # whole repo  -> GitHub
#   ./deploy_space.sh all <app>                        # both: GitHub first, then the Space
#   <app> is one of: shopping_agent, research_agent, financial_researcher_agent
#   (see app_target() below), or "<folder> <hf_user/space>" for anything else.
#
# Examples:
#   ./deploy_space.sh research_agent                   # -> MiguelBayanSoares/Research_Agent
#   ./deploy_space.sh all shopping_agent
#   ./deploy_space.sh research_agent MiguelBayanSoares/Some_Other_Space
#
# Only COMMITTED changes are deployed. The Space must already exist on huggingface.co.
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

usage() { sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

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
  all)
    shift
    resolve_app "$@"
    warn_uncommitted
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
