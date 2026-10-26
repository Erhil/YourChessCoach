import sqlite3

from app.db import backup


def test_backup_keeps_seven_newest_copies(tmp_path):
    db = tmp_path / "app.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.commit()
    for i in range(9):
        conn.execute("INSERT INTO t VALUES (?)", (i,))
        conn.commit()
        backup(db)
    conn.close()

    copies = sorted((tmp_path / "backups").glob("app-*.db"))
    assert len(copies) == 7
    newest = sqlite3.connect(copies[-1])
    try:
        assert newest.execute("SELECT x FROM t ORDER BY x").fetchall() == [(i,) for i in range(9)]
    finally:
        newest.close()


def test_backup_skips_a_missing_database(tmp_path):
    backup(tmp_path / "app.db")
    backup(":memory:")
    assert not (tmp_path / "backups").exists()
