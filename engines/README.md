# engines/

This folder holds the chess engines and the Maia weights. Git keeps only this file.

- `stockfish/` — the official Stockfish build for your OS and CPU (GPL-3.0).
- `lc0/` — lc0 for the Maia networks (GPL-3.0). Windows gets a release binary; on Linux the script builds it from source (needs g++ and git).
- `maia/` — the Maia weights `maia-1100.pb.gz` to `maia-1900.pb.gz` from https://github.com/CSSLab/maia-chess (GPL-3.0).

`scripts/setup.py` fills this folder. To run only this step, use the Python from `.venv`:

```bash
.venv/bin/python scripts/download_engines.py
```

```powershell
.venv\Scripts\python.exe scripts\download_engines.py
```

A second run does not download the files again. To get one item only, add `--only stockfish`, `--only lc0` or `--only maia`.
If the GitHub API limit stops the download, set the environment variable `GITHUB_TOKEN` to a GitHub token.

Without lc0 or the Maia weights, the opponent uses Stockfish with a limited strength.
