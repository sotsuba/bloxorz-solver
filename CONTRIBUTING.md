# Contributing

1. Create a branch from the latest `main`: `<firstname>/<short-description>`.
2. Keep changes focused and update relevant docs.
3. Run checks:

   ```sh
   uv sync --group dev
   uv run pytest -q
   uv run ruff check .
   ```

4. Use a [Conventional Commit](https://www.conventionalcommits.org/en/v1.0.0/)
   message, such as `feat: add solver playback`.
5. Push the branch and open a PR against `main`. Describe the change and test
   results; use the same title as the main commit. PRs are squash-merged.
