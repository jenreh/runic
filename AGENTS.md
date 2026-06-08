# AGENTS.md

---

## 1) Golden Rules

1. **Think → Memory → Tools → Code → Memory.** Use code-reasoning; search Memory and claude-context first; minimal diff; write learnings back.
2. **Tests are truth.** Failures → fix code first. Change tests only if clearly wrong spec.
3. **Minimal diff.** Add tests before code. Keep simple.
4. **Consistency > cleverness.** Follow SOPs and stack idioms.
5. **Memory multiplies.** Persist decisions, patterns, error signatures, proven fixes.
6. **Files ≤ 1000 lines.** Exceed → refactor (see §5).
7. No extensive docs/summaries/comments unless requested.
8. No `--autogenerate` for Alembic migrations; write manually.
9. No `cat` to create files; use tools.
10. Log default: `logger.debug`. Important events: `logger.info`. Issues only: `logger.warning/error`. **No `print`.**

> Prefer *local* changes over cross-module refactors.

---

## 2) Task Bootstrap Pattern

```markdown
<!-- plan:start
goal: <one line clear goal>
constraints:
- Python 3.13; Reflex UI; FastAPI; SQLAlchemy 2.0; Alembic; Pydantic; appkit_mantine;
- logging: no f-strings in logger calls
- files ≤ 1000 lines; apply design patterns where appropriate
- minimal diff; add/adjust tests first
definition_of_done:
- tests pass; coverage ≥ 80% (non-Reflex classes & Reflex states); lint/type checks clean; memory updated
steps:
1) Search Memory for "<keywords>"
2) Draft/adjust failing test to capture expected behavior
3) Implement minimal code change
4) Run task test; iterate until green
5) Update Memory: decisions, patterns, error→fix
plan:end -->
```

---

## 3) Tooling Decision Matrix

| Situation | Primary | Secondary | Store to Memory |
| --- | --- | --- | --- |
| API/pattern uncertainty | **Context7** | — | Canonical snippet + link; edge cases |
| Ecosystem bug/issue | **DuckDuckGo** | Context7 | Minimal repro; versions; workaround |
| Repeated test failure | **Memory (search)** | Context7 | Error signature → fix; root cause |
| New feature scaffold | **Context7** | — | How‑to snippet; checklist |
| House style/tooling | **This file** | Context7 | Checklist results |

Prefer official docs; widen via web search for cross-version issues.

---

## 4) SOP — Development Workflow

**Task Runner:** `task` (via `Taskfile.dist.yml`), not `make`.

### Prepare

1. Memory first — search prior solutions.
2. Reasoning plan — Task Bootstrap Pattern.
3. `task sync` (uv, Python 3.13).
4. `task test` — snapshot current failures.

### Triage Failures

- Read first failing assertion; map to spec.
- Tests match spec → fix code. Diverge → document; adjust spec/tests (after approval).
- Add/adjust unit tests to codify expected behavior.

### Implement (Minimal Diff)

- Tests-first for new behavior. Approved stacks only. Apply design patterns (see §5).
- **No `print`.** Use `logging` module.
- **No f-strings in logger calls:**

  ```python
  import logging

  log = logging.getLogger(__name__)
  log.info("Loaded items: %d", count)  # ✅
  # log.info(f"Loaded items: {count}") # ❌
  ```

- After every code change, run `task lint` — not just at PR time.

### Quality Gates

- `task lint`, `task format`, `task typecheck`.
- `task test` — coverage ≥ **80%** non-Reflex classes & Reflex states.

### Learn → write to **Memory**

### Dependencies

- add dependencies always be using `uv add <library name>`

---

## 5) Python Code & Testing

Full rules in **python-coding** skill. Key:

- Python 3.14; uv; line length **88**.
- No f-strings in logger calls.
- Files **≤ 1000 lines**.
- Test coverage ≥ 80%.
- Type annotations on **all** functions/methods.

---

## 6) Security & Config

- No credentials in code/history; `.env` local, Key Vault prod.
- Non-secret YAML; env `__` override pattern.
- Parameterized logs; no sensitive values.
- `SecretStr` → `.get_secret_value()`.
- Update vulnerable deps; document CVE-driven updates in commits & Memory.

---

## 7) Search SOPs

- **Context7 first** for framework truths; cite in Memory.
- **DuckDuckGo** for cross-version issues; prefer official docs.
- Store only final answer: minimal snippet + rationale + version pins + link.

---

## 8) Task Checklist / Definition of Done

- [ ] Tests added/updated; all green
- [ ] Coverage ≥ 80%
- [ ] `task format && task lint && task typecheck` pass
- [ ] No file > 1000 lines
- [ ] Clean architecture, no code smells, used python-clean-code principles
- [ ] Migrations reviewed & documented
- [ ] Documentation & README.md updated
- [ ] Memory updated (decisions, patterns, error→fix, learnings)

---

## 9) Important Skills

| Skill | Purpose |
| --- | --- |
| `python-coding` | Python 3.14 style, logging, type annotations, design patterns, testing |
| `python-clean-code` | Enforce Clean Code Developer (CCD) architecture and software quality principles |
| `code-cleanup` | Refactor and simplify Python files modified in the current session if they get complex/big |
| `boost` | Use when the user wants to refine, sharpen, or expand a rough idea into a detailed implementation prompt |
