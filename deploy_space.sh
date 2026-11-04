#!/usr/bin/env bash
# Push one unit folder as the root of a Hugging Face Space.
# Usage: ./deploy_space.sh <unit_path> <hf_user/space_name>
#   e.g. ./deploy_space.sh unit1/agent_shopping_list MiguelBayanSoares/shopping_list
# Only COMMITTED changes are deployed. Uses $HF_TOKEN if set, otherwise your git credentials.
set -euo pipefail

UNIT_PATH="${1:?unit path, e.g. unit1/agent_shopping_list}"
SPACE="${2:?space id, e.g. MiguelBayanSoares/shopping_list}"
BRANCH="space-deploy-$(echo "$UNIT_PATH" | tr '/' '-')"

if [[ -n "${HF_TOKEN:-}" ]]; then
  URL="https://${SPACE%%/*}:${HF_TOKEN}@huggingface.co/spaces/${SPACE}"
else
  URL="https://huggingface.co/spaces/${SPACE}"
fi

git subtree split --prefix="$UNIT_PATH" -b "$BRANCH"
git push --force "$URL" "$BRANCH:main"
git branch -D "$BRANCH"
echo "Deployed $UNIT_PATH -> https://huggingface.co/spaces/$SPACE"
