---
name: Bug report
about: Report a problem with a loader or the pipeline
title: "[Bug] "
labels: bug
assignees: ''
---

## Describe the bug

A clear and concise description of what went wrong.

## Loader / command affected

Which loader (`--loader ciqual`, `--loader off`, etc.) or is this an issue
with `main.py` / `db/` in general?

## Steps to reproduce

1. Run `python main.py --loader ...`
2. ...
3. See error

## Expected behavior

What you expected to happen.

## Actual behavior

What actually happened. Include the full stack trace or log output.

```
paste log/stack trace here
```

## Environment

- OS:
- Python version (`python --version`):
- `pocket-nutrition/data` commit / tag:
- PostgreSQL version:
- Installed via: (pip / Docker)

## Additional context

Anything else that might help — e.g. whether the upstream source file
format changed, `DOWNLOAD_DIR` cache state, `--force` used or not.
