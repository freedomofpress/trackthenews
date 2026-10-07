set shell := ["bash", "-euo", "pipefail", "-c"]

# pipx installs poetry to ~/.local/bin, which may not be on PATH yet
poetry := env("POETRY", `command -v poetry || echo "$HOME/.local/bin/poetry"`)
# Prefer the Python version CI tests against
python := env("PYTHON", `command -v python3.13 || echo python3`)

_default:
    @just --list

# Install poetry (via pipx) and dev dependencies; idempotent, ~2s when current
dev:
    @command -v {{ poetry }} >/dev/null || pipx install poetry
    @{{ poetry }} env use --quiet {{ python }}
    @{{ poetry }} install --quiet --with=dev

# Offline tests; all HTTP is stubbed from tests/fixtures
test *args: dev
    @{{ poetry }} run pytest {{ args }}

# Smoke test against real feeds; needs network, never publishes
test-integration *args: dev
    @{{ poetry }} run pytest -m live {{ args }}

alias integration := test-integration

# Lint and check formatting
ruff: dev
    @{{ poetry }} run ruff check
    @{{ poetry }} run ruff format --check

# Fix lint and formatting issues
ruff-fix: dev
    @{{ poetry }} run ruff check --fix
    @{{ poetry }} run ruff format

alias lint := ruff
