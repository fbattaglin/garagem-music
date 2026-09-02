---
paths:
  - "**/*.py"
---

# Python style

- Type hints on every public signature. `mypy --strict` must pass.
- `pydantic.BaseModel` for data crossing layers; `dataclass(frozen=True)` for internal
  domain values.
- No `Any` without a comment explaining why.
- No `print()` — use the structured logger in `obs/`.
- Docstrings only where the "why" is not obvious. Do not document what the code says.
- Functions longer than ~40 lines are usually doing two things.
- English for identifiers, comments and docstrings, without exception.
