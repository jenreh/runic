# Contributing to runic

Thank you for your interest in contributing! This guide covers everything you need to get started as a developer.

---

## Required Tools

Before you begin, install the following tools:

### [uv](https://docs.astral.sh/uv/getting-started/installation/)

`uv` is the Python package and project manager used by this project.

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### [Task](https://taskfile.dev/installation/)

`task` is the task runner used instead of `make`.

```bash
# macOS (Homebrew)
brew install go-task

# Linux (shell script)
sh -c "$(curl --location https://taskfile.dev/install.sh)" -- -d -b ~/.local/bin

# Windows (Scoop)
scoop install task

# Or via Go
go install github.com/go-task/task/v3/cmd/task@latest
```

Verify both tools are available:

```bash
uv --version
task --version
```

---

## Project Setup

```bash
# 1. Clone the repository
git clone https://github.com/jenreh/runic.git
cd runic

# 2. Initialize the project (installs Python, syncs dependencies, sets up pre-commit hooks)
task init
```

`task init` handles everything:

- Installs the correct Python version (from `pyproject.toml`)
- Pins the version locally via `.python-version`
- Syncs all dependencies (including dev extras) via `uv sync`
- Installs and configures `pre-commit` hooks

To see all available commands at any time:

```bash
task
```

---

## Development Workflow

### Running Tests

```bash
task test
```

Coverage must stay at or above **80%** for all non-trivial code.

### Linting and Formatting

```bash
task lint       # check for lint errors
task format     # auto-fix and format
```

Always run `task format && task lint` before committing. The pre-commit hooks enforce this automatically.

### Type Checking

```bash
task typecheck
```

### Full Quality Gate

```bash
task format && task lint && task typecheck && task test
```

---

## Branching Strategy

All branches must match one of the allowed patterns:

| Branch type | Pattern | Example |
|---|---|---|
| New feature | `feature/<slug>` | `feature/add-node-index-support` |
| Bug fix | `fix/<ticket-ref-and-slug>` | `fix/3-test` |
| Hotfix | `hotfix/<slug-or-version>` | `hotfix/fix-cli-exit-code` |
| Documentation | `docs/<slug>` | `docs/update-migration-guide` |
| Release | `release/<version>` | `release/1.3.0` |

**Naming rules:**

- Lowercase only
- Use `/` exactly as shown above
- Use kebab-case for descriptive parts
- Use digits and dots for version numbers
- Keep names short and specific

Branches that do not match these patterns must be renamed before pushing or opening a pull request.

Examples:

- `feature/add-task-runner-docs`
- `fix/3-test` — branch for "issue #3"
- `hotfix/fix-taskfile-typo`

---

## Contribution Rules

### Commits

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```text
feat: add support for edge property indexes
fix: handle missing label in schema diff
fix(#3): resolve test issue reported in issue tracker
docs: update migration quickstart
refactor: extract CypherBuilder into own module
test: add coverage for rollback edge case
chore: bump falkordb to 1.7.0
```

### Pull Requests

- Open PRs against `main` (features and fixes) or the active `release/*` branch when relevant.
- Fill in the PR description: what changed, why, and how to test it.
- Reference issues with `Closes #3` (e.g. [issue #3](https://github.com/jenreh/runic/issues/3)) where applicable.
- Include screenshots or CLI output for user-visible changes.
- All quality gates must pass before review.

### Code Style

- Python 3.14; line length 88 (enforced by ruff).
- Type annotations on all functions and methods.
- No `print` — use `logging` with `%`-style formatting:

  ```python
  log.info("Processing %d nodes", count)  # correct
  log.info(f"Processing {count} nodes")  # wrong
  ```

- Files must not exceed 1000 lines — refactor if approaching the limit.
- Tests go in `tests/`; aim for ≥ 80% coverage on new code.
- Write tests before or alongside implementation, not after.

### Dependencies

Add dependencies using `uv`:

```bash
uv add <package>          # runtime dependency
uv add --dev <package>    # development-only dependency
```

Do not edit `pyproject.toml` or `uv.lock` manually for dependency changes.

---

## Pre-commit Hooks

Pre-commit hooks are installed by `task init` and run automatically on every commit. To run them manually:

```bash
uv run pre-commit run --all-files
```

---

## Reporting Issues

Please open an issue on [GitHub](https://github.com/jenreh/runic/issues) with:

- A clear description of the problem or feature request
- Steps to reproduce (for bugs)
- The output of `uv run runic --version` and your Python version
