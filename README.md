# agy-skills

**Inspect, search, diagnose, and manage Agent Skills for Google Antigravity (`agy`) via CLI, interactive TUI, and a localhost web dashboard.**

English | [简体中文](./README.zh-CN.md)

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-zero%20(stdlib)-brightgreen.svg)](#installation)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

---

## Why `agy-skills`?

As your Antigravity (`agy`) setup grows across global skills, plugins, `skills.json` mounts (e.g., `.omp` or shared team libraries), and workspace `.agents/skills/`, it quickly becomes hard to answer four simple questions:

1. **Which skills are actually active** right now, and which ones are shadowed or excluded?
2. **Which skills require explicit `/skill-name` invocation** (`disable-model-invocation: true`) vs. which ones auto-trigger on every turn?
3. **What does each skill do**, what helper scripts/references does it bundle, and how many resident tokens do auto-triggered descriptions consume?
4. **Are there subtle frontmatter bugs** (such as camelCase `disableModelInvocation: true`, which `agy` ignores)?

`agy-skills` mirrors Antigravity's exact multi-tier discovery & precedence rules using **pure Python standard library** (zero third-party runtime dependencies).

---

## Features

- **Exact Antigravity Discovery & Precedence**:
  1. Workspace hierarchical (`.agents/skills`, `.agent/skills`, `_agents/skills`, `_agent/skills`, walking up to `.git` root)
  2. Workspace declared (`.agents/skills.json`, `.agent/skills.json`)
  3. Global native (`~/.gemini/config/skills/`, plus CLI/IDE global paths)
  4. Installed plugins (`~/.gemini/config/plugins/*/skills/`, respecting disabled plugins)
  5. Built-in skills (`~/.gemini/antigravity-cli/builtin/skills/`)
  6. Global declared (`~/.gemini/config/skills.json` with `inherits`, `include_only`, and `exclude` patterns)
- **Clear Invocation Mode Badges**: Distinguishes `auto + /cmd`, `explicit /cmd` (`disable-model-invocation: true`), `auto-only` (`disable-slash-command: true`), `shadowed`, and `excluded`.
- **One-Command Mode Switching**: Safely toggle `disable-model-invocation` with atomic file writes (preserving leading HTML comments, formatting, and Markdown bodies).
- **Health Diagnostics (`doctor`)**: Surfaces shadowed duplicates, `skills.json` exclusions, camelCase `disableModelInvocation` bugs, broken symlinks, and estimated resident prompt tokens per turn.
- **Three Interfaces**:
  - **CLI**: CJK-width-aligned colored tables + `--json` output for scripting.
  - **Interactive TUI (`agy-skills tui`)**: Zero-dependency `curses` browser with search, filters, `SKILL.md` reader, and inline mode toggling (works seamlessly over SSH).
  - **Local Web Dashboard (`agy-skills web`)**: Hardened `127.0.0.1`-only single-page UI with live search, filtering, full `SKILL.md` preview, EN/中文 switcher, nonce-based strict CSP, and CSRF-protected mode toggles.
- **Bilingual UI**: Switch between English and Simplified Chinese via `--lang en|zh`, `AGY_SKILLS_LANG=zh`, or the built-in Web toggle button.

---

## Installation

Requires **Python 3.10+** (zero third-party dependencies).

### Option 1: One-Line Installer (Recommended for Linux / macOS)

```bash
curl -fsSL https://raw.githubusercontent.com/Bowen-0x00/agy-skills/main/install.sh | bash
```

Custom install prefix or uninstall:

```bash
# Install to a custom directory
curl -fsSL https://raw.githubusercontent.com/Bowen-0x00/agy-skills/main/install.sh | bash -s -- --prefix "$HOME/bin"

# Uninstall
curl -fsSL https://raw.githubusercontent.com/Bowen-0x00/agy-skills/main/install.sh | bash -s -- --uninstall
```

### Option 2: `pipx` / `uv tool` / `pip`

```bash
# pipx
pipx install git+https://github.com/Bowen-0x00/agy-skills.git

# uv
uv tool install git+https://github.com/Bowen-0x00/agy-skills.git

# pip (user install)
pip install --user git+https://github.com/Bowen-0x00/agy-skills.git
```

### Option 3: Clone & Run Directly

```bash
git clone https://github.com/Bowen-0x00/agy-skills.git
cd agy-skills
pip install -e .
# Or run without installing:
python3 src/agy_skills/cli.py
```

---

## Quick Start & Usage

```bash
# List all active user & plugin skills (hides built-in skills by default)
agy-skills

# Show only skills that require explicit /skill-name invocation
agy-skills -e
agy-skills list --explicit

# Show only auto-triggered skills
agy-skills -a

# Include Antigravity built-in skills, or show shadowed/excluded entries too
agy-skills --builtin
agy-skills --all

# Wrap full descriptions or export structured JSON
agy-skills --full
agy-skills list --all --json

# Filter by source (global | plugin | declared | workspace | builtin | omp)
agy-skills list --source plugin

# Search across skill names and descriptions (add --body to search SKILL.md bodies)
agy-skills search latex
agy-skills search citation --body

# Inspect one skill in detail (scripts, references, resolved symlink path, warnings)
agy-skills show citation-grounding-checker
agy-skills show citation-grounding-checker --body

# Toggle invocation mode (explicit <-> auto), then run `/skills reload` inside agy
agy-skills mode citation-grounding-checker auto
agy-skills mode paper-review-polisher explicit
agy-skills mode paper-review-polisher toggle

# Audit configuration warnings, shadowed skills, and resident context budget
agy-skills doctor

# Launch interactive terminal TUI
agy-skills tui

# Launch localhost-only web dashboard (default port 8765)
agy-skills web
agy-skills web --port 9000

# Switch interface language (or set export AGY_SKILLS_LANG=zh)
agy-skills --lang zh
```

> **Remote SSH Tip**: When running `agy-skills web` on a remote Linux host, forward the loopback port from your local machine:
> ```bash
> ssh -L 8765:127.0.0.1:8765 user@your-host
> ```
> Then open `http://127.0.0.1:8765` in your local browser.

### TUI Keybindings (`agy-skills tui`)

| Key | Action |
| :--- | :--- |
| `↑` / `↓` or `j` / `k` | Navigate skill list |
| `/` | Live search filter (`Enter` confirm, `Esc` clear) |
| `e` / `t` / `a` | Filter: Explicit `/cmd` only / Auto-triggered only / All modes |
| `b` / `x` | Toggle built-in skills / shadowed & excluded skills |
| `v` or `Enter` | Open scrollable full `SKILL.md` viewer |
| `m` | Toggle `disable-model-invocation` (`y`/`n` confirmation) |
| `r` | Rescan disk |
| `q` | Quit |

---

## Security Design (`agy-skills web`)

- Binds **strictly to `127.0.0.1`** (never exposes a wildcard listener).
- Enforces per-request **nonce-based Content Security Policy** (no `unsafe-inline` or `unsafe-eval`), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, and `Cache-Control: no-store`.
- Protects `POST /api/mode` with strict **`Origin` verification**, per-session **cryptographic CSRF synchronizer tokens**, request rate limiting, and allow-listed HTTP methods (`GET`/`POST` only).
- Resolves editable targets strictly from the discovered skill registry with path-boundary checks (never trusts raw filesystem paths from HTTP parameters).
- Frontend renders exclusively via `document.createElement` and `textContent` (zero `innerHTML` or native browser dialogs).

---

## Development & Testing

```bash
python3 -m unittest discover -s tests -v
```

---

## License

Released under the [MIT License](./LICENSE).

---

🌐 Looking for Chinese documentation? See [README.zh-CN.md](./README.zh-CN.md).
