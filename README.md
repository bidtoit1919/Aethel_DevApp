# Aethel

A hub for AI-assisted development: projects, models and coding agents in one
window, with a ledger of what happened. Agents run inside the app, with their
own interface untouched, signed in with the accounts you already have (Claude,
ChatGPT, Google, Grok and more, through each provider's own app) or API keys.
Everything stays on your computer; Aethel has no servers.

Aethel comes in two editions with the same pages and features:

| Edition | Folder | Built on | Start here |
| --- | --- | --- | --- |
| Linux (GNOME) | [`linux/`](linux/) | GTK 4, libadwaita, VTE, libsecret | [linux/README.md](linux/README.md) |
| Windows | [`windows/`](windows/) | GTK 4 and libadwaita through MSYS2, ConPTY + pyte, Credential Manager | [windows/README.md](windows/README.md) |

Each folder is a complete, self-contained project with its own `src/`,
`data/`, `tests/` and `pyproject.toml`. The application code is the same
apart from each edition's platform layer; the Windows README has a table of
what differs.

## Quick start

Linux:

```bash
cd linux && PYTHONPATH=src python3 -m aethel
```

Windows (PowerShell, from the repository root):

```powershell
powershell -ExecutionPolicy Bypass -File windows\scripts\install.ps1
```

## Tests

```bash
cd linux && PYTHONPATH=src python3 -m unittest discover -s tests -v
```

```bat
windows\scripts\test.cmd
```
