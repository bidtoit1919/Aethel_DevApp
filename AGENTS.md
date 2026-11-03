# Agent Notes

This repository holds two editions of Aethel. Work inside the edition you are changing and follow its own notes (`linux/AGENTS.md`, `windows/AGENTS.md`); each is self-contained with its own `src/`, `data/`, `tests/` and `pyproject.toml`. There is no shared package — application code is duplicated between the editions, so a change must be applied in both by hand.

Rules for both:

- The editions share their application code apart from the platform layer (`windows/src/aethel/winplat.py`, the terminal widget in each `views/console.py`, `terminal.py`, and the secret, shell and path code those call). A feature or fix outside the platform layer belongs in both editions, in the same commit.
- Keep the database schema and its `PRAGMA user_version` migrations identical in both `src/aethel/db.py` files.
- Keep the agents' sign-ins and recipes in both `data/agents.toml` files identical; only `install` lines differ.
- Subscription sign-ins go only through each provider's own CLI and documented commands; Aethel never implements a provider's OAuth, reads CLI credentials, or calls subscription models itself (see Accounts in each edition's AGENTS.md).
- Run both test suites before committing: `cd linux && PYTHONPATH=src python3 -m unittest discover -s tests -v` and the same from `windows/` (Windows-only tests skip on Linux). There is no lint, formatter, typecheck or CI; these suites are the gate.
- API keys and secrets go to the platform's secret store (libsecret or Credential Manager), never the database, ledger, sources or fixtures.
- `.gitattributes` forces CRLF for `*.cmd` and `*.ps1`; keep Windows scripts CRLF.
