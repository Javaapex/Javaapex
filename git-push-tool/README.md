# JavaAPEX Git Push Tool

A zero-dependency standalone CLI to push any local folder to a new GitHub repo.  
Uses the same `GITHUB_TOKEN` and proxy config from `../JavaAPEX-Backend/.env`.

## Quick Start

```bash
# Push the entire JavaAPEX project
cd git-push-tool
python push.py

# Push with a custom repo name
python push.py --name JavaAPEX --owner qlikaccel

# Push a specific folder
python push.py C:\path\to\folder --name my-project

# Create a private repo
python push.py --private

# Push to a specific branch
python push.py --branch develop
```

## Options

| Flag | Description | Default |
|---|---|---|
| `local_path` | Directory to push (positional) | `../` (JavaAPEX root) |
| `--name` | Repository name | `<folder>-YYYYMMDD-HHMMSS` |
| `--owner` | GitHub org or username | Auto-detected from token |
| `--token` | GitHub PAT | From `.env` |
| `--private` | Create private repo | `false` |
| `--branch` | Branch name | `main` |
| `--message` | Commit message | Auto-generated |

## No Dependencies

This tool uses only Python standard library (`urllib`, `subprocess`, `json`).  
No `pip install` required – just run it with any Python 3.10+.
