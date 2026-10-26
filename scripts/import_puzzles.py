"""Import a stratified subset of the Lichess puzzle Parquet files into data/puzzles.db.

Base filter, then the most played puzzles in each 100-point rating bucket."""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

DATA = Path(__file__).resolve().parent.parent / "data"
SRC = DATA / "puzzles-src"
DB = DATA / "puzzles.db"

SCHEMA = """
CREATE TABLE puzzles (id TEXT PRIMARY KEY, fen TEXT NOT NULL, moves TEXT NOT NULL,
  rating INTEGER, rating_deviation INTEGER, popularity INTEGER, nb_plays INTEGER,
  themes TEXT, opening_tags TEXT);
CREATE TABLE puzzle_themes (puzzle_id TEXT NOT NULL, theme TEXT NOT NULL);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE src AS SELECT * FROM puzzles WHERE 0;
"""


def rows(files: list[Path], a):
    """Yield filtered rows as dicts, reading each Parquet file in batches."""
    cols = [
        "PuzzleId",
        "FEN",
        "Moves",
        "Rating",
        "RatingDeviation",
        "Popularity",
        "NbPlays",
        "Themes",
        "OpeningTags",
    ]
    for f in files:
        for batch in pq.ParquetFile(f).iter_batches(batch_size=50000, columns=cols):
            mask = pc.and_(
                pc.and_(
                    pc.greater_equal(batch["Popularity"], a.min_popularity),
                    pc.greater_equal(batch["NbPlays"], a.min_plays),
                ),
                pc.and_(
                    pc.greater_equal(batch["Rating"], a.min_rating),
                    pc.less_equal(batch["Rating"], a.max_rating),
                ),
            )
            yield from batch.filter(mask).to_pylist()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-popularity", type=int, default=85)
    ap.add_argument("--min-plays", type=int, default=200)
    ap.add_argument(
        "--per-bucket", type=int, default=17500, help="max puzzles per 100-point bucket"
    )
    ap.add_argument("--min-rating", type=int, default=400)
    ap.add_argument("--max-rating", type=int, default=2400)
    ap.add_argument("--count-only", action="store_true", help="only print how many rows pass")
    a = ap.parse_args()
    try:
        files = sorted(SRC.glob("*.parquet"))
        if not files:
            raise RuntimeError(f"no .parquet files in {SRC}; run scripts/download_puzzles.py")
        flt = {
            "min_popularity": a.min_popularity,
            "min_plays": a.min_plays,
            "min_rating": a.min_rating,
            "max_rating": a.max_rating,
            "per_bucket": a.per_bucket,
        }
        meta = {
            "source_size": str(sum(f.stat().st_size for f in files)),
            "filter": json.dumps(flt, sort_keys=True),
        }

        if a.count_only:
            print("count:", sum(1 for _ in rows(files, a)), flt)
            return 0
        if DB.exists():
            try:
                con = sqlite3.connect(DB)
                cur = dict(con.execute("SELECT key, value FROM meta"))
                n = con.execute("SELECT COUNT(*) FROM puzzles").fetchone()[0]
                con.close()
                if all(cur.get(k) == v for k, v in meta.items()):
                    print(f"up to date: {n} puzzles")
                    print(f"puzzles: OK {n} in data/puzzles.db")
                    return 0
            except sqlite3.Error:
                pass
        t0 = time.time()
        tmp = DB.with_name("puzzles.db.tmp")
        tmp.unlink(missing_ok=True)
        con = sqlite3.connect(tmp)
        con.executescript(SCHEMA)
        ins = "INSERT INTO src VALUES (?,?,?,?,?,?,?,?,?)"
        pb = []
        with con:
            for r in rows(files, a):
                pb.append(
                    (
                        r["PuzzleId"],
                        r["FEN"],
                        r["Moves"],
                        r["Rating"],
                        r["RatingDeviation"],
                        r["Popularity"],
                        r["NbPlays"],
                        " ".join(r["Themes"] or []),
                        " ".join(r["OpeningTags"] or []),
                    )
                )
                if len(pb) >= 50000:
                    con.executemany(ins, pb)
                    pb = []
            con.executemany(ins, pb)
            con.execute(
                "INSERT INTO puzzles SELECT id, fen, moves, rating, rating_deviation, popularity,"
                " nb_plays, themes, opening_tags FROM (SELECT *, ROW_NUMBER() OVER"
                " (PARTITION BY rating / 100 ORDER BY nb_plays DESC, id) AS rn FROM src)"
                " WHERE rn <= ?",
                (a.per_bucket,),
            )
            tb = []
            for pid, themes in con.execute("SELECT id, themes FROM puzzles"):
                tb += [(pid, t) for t in themes.split()]
            con.executemany("INSERT INTO puzzle_themes VALUES (?,?)", tb)
            con.execute("DROP TABLE src")
            con.execute("CREATE INDEX idx_puzzles_rating ON puzzles(rating)")
            con.execute("CREATE INDEX idx_themes ON puzzle_themes(theme, puzzle_id)")
            con.executemany("INSERT INTO meta VALUES (?,?)", meta.items())
            n = con.execute("SELECT COUNT(*) FROM puzzles").fetchone()[0]
        con.execute("VACUUM")
        con.close()
        tmp.replace(DB)
        print(f"puzzles: OK {n} in data/puzzles.db ({time.time() - t0:.0f} s)")
        return 0
    except (OSError, RuntimeError, sqlite3.Error, pa.ArrowException) as e:
        print(f"puzzles: FAIL {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
