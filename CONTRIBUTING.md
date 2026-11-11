# Contributing

Thanks for considering a contribution!

## Before you open a PR

- **Never commit** real host addresses, usernames, SSH keys, API tokens, DeepSeek
  login profiles, or personal absolute paths. Use `*.example.sh` files and
  environment variables instead.
- Keep changes scoped: `app/` (Python), `engine/` (bash/PowerShell), `docs/`.
- Run a quick syntax check:

```bash
python -m compileall -q app run_gui.pyw
find engine -name '*.sh' -print0 | xargs -0 -n1 bash -n
```

## Reporting issues

Please include:

- Windows version / Python version;
- which module (COMSOL submitter / papers→reports);
- the relevant log lines (mask hostnames and paths);
- whether it reproduces in **M 演示模式** (no COMSOL needed).

## Pull requests

- One logical change per PR;
- Update `README.md` / `docs/` when behavior changes;
- Do not add new mandatory dependencies without updating `requirements.txt` and
  `THIRD_PARTY_NOTICES.md`.
