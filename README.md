# Hugging Face Agents Course

Each unit lives in its own folder and is deployed as its own Hugging Face Space.
The Space config (YAML front matter) lives in each unit's `README.md`, not here.

| Unit | Folder | Space |
|------|--------|-------|
| 1 | `unit1/agent_shopping_list` | [MiguelBayanSoares/shopping_list](https://huggingface.co/spaces/MiguelBayanSoares/shopping_list) |

## Deploying

- **Automatically:** every push to `main` on GitHub runs `.github/workflows/deploy-spaces.yml`
  (needs an `HF_TOKEN` repo secret with write access). Add a matrix entry per new unit.
- **Manually:** commit, then `./deploy_space.sh unit1/agent_shopping_list MiguelBayanSoares/shopping_list`
