"""WAL-safe SQLite backup and restore.

    python scripts/backup.py backup  [--db PATH] [--out DIR] [--keep N]
    python scripts/backup.py restore BACKUP_FILE [--db PATH] [--force]

`backup` uses SQLite's online backup API, so it is consistent while the app is writing (a plain file copy of a WAL
database can be torn). Backups are verified with PRAGMA integrity_check before they are kept.
"""

import argparse
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "alphabridge.db"


def _check(path: Path) -> None:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        result = con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()
    if result != "ok":
        raise RuntimeError(f"integrity check failed for {path}: {result}")


def backup(db: Path, out_dir: Path, keep: int = 14) -> Path:
    if not db.exists():
        raise FileNotFoundError(db)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{db.stem}-{datetime.now(UTC):%Y%m%dT%H%M%S%f}Z.db"
    src, dst = sqlite3.connect(db), sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    try:
        _check(dest)
    except RuntimeError:
        dest.unlink(missing_ok=True)
        raise
    for old in sorted(out_dir.glob(f"{db.stem}-*.db"))[:-keep] if keep > 0 else []:
        old.unlink()
    return dest


def restore(backup_file: Path, db: Path, force: bool = False) -> Path:
    _check(backup_file)
    if db.exists() and not force:
        raise FileExistsError(f"{db} exists; stop the app and pass --force to overwrite (a .pre-restore copy is kept)")
    if db.exists():
        safety = db.with_suffix(".pre-restore")
        src, dst = sqlite3.connect(db), sqlite3.connect(safety)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
    for sidecar in (db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")):
        sidecar.unlink(missing_ok=True)  # stale WAL from the old database must not be replayed onto the restored one
    db.parent.mkdir(parents=True, exist_ok=True)
    src, dst = sqlite3.connect(f"file:{backup_file}?mode=ro", uri=True), sqlite3.connect(db)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    _check(db)
    return db


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup")
    b.add_argument("--db", type=Path, default=DEFAULT_DB)
    b.add_argument("--out", type=Path, default=DEFAULT_DB.parent / "backups")
    b.add_argument("--keep", type=int, default=14, help="newest N backups to retain (0 = keep all)")
    r = sub.add_parser("restore")
    r.add_argument("file", type=Path)
    r.add_argument("--db", type=Path, default=DEFAULT_DB)
    r.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    try:
        path = backup(a.db, a.out, a.keep) if a.cmd == "backup" else restore(a.file, a.db, a.force)
    except (OSError, RuntimeError, sqlite3.Error) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
