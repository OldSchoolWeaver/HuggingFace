# Hugging Face Agents Course

Each unit lives in its own folder and is deployed as its own Hugging Face Space.
The Space config (YAML front matter) lives in each unit's `README.md`, not here.

| Unit | Folder | Space |
|------|--------|-------|
| 1 | `unit1/agent_shopping_list` | [MiguelBayanSoares/shopping_list](https://huggingface.co/spaces/MiguelBayanSoares/shopping_list) |
| 2 | `unit2/research_agent` | [MiguelBayanSoares/Research_Agent](https://huggingface.co/spaces/MiguelBayanSoares/Research_Agent) |

## Deploying

- **Automatically:** every push to `main` on GitHub runs `.github/workflows/deploy-spaces.yml`
  (needs an `HF_TOKEN` repo secret with write access). Add a matrix entry per new unit.
- **Manually** (commit first; `./deploy_space.sh --help` for details):
  ```bash
  ./deploy_space.sh unit1        # unit 1 -> MiguelBayanSoares/shopping_list
  ./deploy_space.sh unit2        # unit 2 -> MiguelBayanSoares/Research_Agent
  ./deploy_space.sh github       # repo   -> GitHub
  ./deploy_space.sh all unit2    # GitHub, then the unit 2 Space
  ```
