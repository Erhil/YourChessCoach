# data/

This folder holds downloaded data and the app database. Git keeps only this file.

- `puzzles-src/*.parquet` — the Lichess puzzle set, source files (about 850 MB).
- `puzzles.db` — the filtered puzzle database (SQLite, read-only, about 135 MB).
- `openings.tsv` — Lichess opening names.
- `app.db` — users and their progress. Do not delete it.
- `backups/` — copies of `app.db`. The server makes one at each start and keeps the last 7.
- `bench/` — results of `scripts/bench_models.py` for the model comparison.
- `app.log` — the log, when the Windows autostart task from README.md runs the app.

`scripts/setup.py` fills this folder. To get only the puzzles, use the Python from `.venv`:

```bash
.venv/bin/python scripts/download_puzzles.py
.venv/bin/python scripts/import_puzzles.py
```

```powershell
.venv\Scripts\python.exe scripts\download_puzzles.py
.venv\Scripts\python.exe scripts\import_puzzles.py
```

The default import filter: Popularity 85 or more, NbPlays 200 or more, rating 400 to 2400,
and at most 17,500 most played puzzles in each 100-point rating bucket.
`import_puzzles.py --help` shows the options.

Sources and licenses: the Lichess puzzle set on Hugging Face
(https://huggingface.co/datasets/Lichess/chess-puzzles, CC0) and
https://github.com/lichess-org/chess-openings (CC0).
