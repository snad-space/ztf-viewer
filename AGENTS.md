# Repository Guidelines

## Project Structure & Module Organization
- Main application code lives in `ztf_viewer/`.
- Route/page handlers are in `ztf_viewer/pages/`; catalog integrations are in `ztf_viewer/catalogs/`; light-curve data logic is in `ztf_viewer/lc_data/`.
- Static frontend files are split between `ztf_viewer/assets/` (Dash assets) and `ztf_viewer/static/` (JS/images).
- Tests live in `tests/`, with subpackages mirroring app structure (for example, `tests/catalogs/conesearch/`).
- Container and deployment files are in the repo root (`Dockerfile`, `docker-compose*.yml`) plus `proxy/` and `proxy-cache-filler/`.

## Build, Test, and Development Commands
- Dependencies are managed with [`uv`](https://docs.astral.sh/uv/) and pinned in `uv.lock` (see `README.md`); `uv run <cmd>` syncs the `.venv` from the lockfile before running.
- `uv run python -m ztf_viewer`: run the app locally (set `CACHE_TYPE=memory` and `UNAVAILABLE_CATALOGS_CACHE_TYPE=memory` for local runs).
- `uv run --group tests pytest`: run the Python test suite from `tests/` (`tests` is a `uv` dependency group, not included by default).
- `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build`: start the local dev stack.
- `pre-commit run --all-files`: run formatting and repository hygiene checks.

## Coding Style & Naming Conventions
- Python 3.12 is required (`pyproject.toml`).
- Use 4-space indentation and keep lines within 120 chars.
- Formatting: `black`; linting: `ruff` (with some per-file `F401` exceptions in package `__init__.py` files).
- Use `snake_case` for functions/modules, `PascalCase` for classes, and keep file names descriptive by domain (for example, `catalogs/conesearch/tns.py`).

## Testing Guidelines
- Framework: `pytest` with tests discovered under `tests/`.
- Name tests as `test_*.py`; mirror module behavior in file names (for example, `test_ttl_set_redis_ttl_set.py`).
- Add regression tests for bug fixes and edge cases, especially around external catalog adapters and caching logic.
- CI runs tests via Docker (`.github/workflows/test.yml`), so keep local results reproducible in containerized runs.

## Commit & Pull Request Guidelines
- Prefer concise, imperative commit messages (examples in history: `Update deps`, `Update docker infra`).
- Group related changes per commit; avoid mixing refactors and behavior changes without clear rationale.
- PRs should include: purpose summary, linked issue(s), test evidence (`pytest` or Docker test output), and screenshots for UI-visible changes.
- Ensure `pre-commit` and tests pass before requesting review.
