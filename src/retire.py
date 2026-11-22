"""Move derived files out of the way before a stage is re-run with changed rules (decision D22).

The never-overwrite writer puts a changed output beside the old one, so the
next stage would still read the old file. This script moves named files from
``data/interim/`` into ``data/interim/retired/<UTC>/``. Nothing is deleted
or replaced; each file's size and SHA-256 are recorded.

    python src/retire.py data/interim/trips_clean.parquet data/interim/trips_excluded.parquet

Writes ``data/interim/retired/<UTC>/`` with the moved files and
``retired.csv``; in ``output/runs/retire/<UTC>/``: ``run.json``; a row in
``logs/runs.csv``. Only files directly in ``data/interim/`` are accepted.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import INTERIM, Run, rel, sha256_file, utc_stamp, write_rows_csv  # noqa: E402

RETIRED = INTERIM / "retired"
FIELDS = ["file", "moved_to", "size_bytes", "sha256"]


def check(paths: list[Path], interim: Path = INTERIM) -> list[Path]:
    """Every path must be an existing file directly in ``interim``, named once."""
    out = []
    for p in paths:
        p = Path(p).resolve()
        if p.parent != interim.resolve():
            raise SystemExit(f"{rel(p)} is not directly in {rel(interim)}; refused")
        if not p.is_file():
            raise SystemExit(f"{rel(p)} does not exist or is not a file")
        if p in out:
            raise SystemExit(f"{rel(p)} named twice")
        out.append(p)
    return out


def retire(paths: list[Path], dest_dir: Path) -> list[dict]:
    """Move each file into ``dest_dir`` without replacing anything (``os.link`` fails if the target exists)."""
    dest_dir.mkdir(parents=True, exist_ok=False)
    rows = []
    for p in paths:
        row = {"file": rel(p), "size_bytes": p.stat().st_size, "sha256": sha256_file(p)}
        target = dest_dir / p.name
        os.link(p, target)
        p.unlink()
        row["moved_to"] = rel(target)
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", type=Path)
    args = ap.parse_args(argv)
    paths = check(args.files)
    run = Run("retire")
    dest = RETIRED / utc_stamp()
    rows = retire(paths, dest)
    write_rows_csv(dest / "retired.csv", rows, FIELDS)
    for r in rows:
        print(f"MOVED {r['file']} -> {r['moved_to']}")
    run.finish({"retired_to": rel(dest), "files": rows})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
