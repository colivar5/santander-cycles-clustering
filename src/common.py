"""Shared paths, seed, the never-overwrite writer and run records.

Every result file goes through ``write_with`` (or a helper built on it):
- the target does not exist: it is written;
- it exists with identical bytes: it is left alone;
- it exists with different bytes: the new content is written beside it as
  ``<stem>.<UTC stamp><suffix>`` and a NOTE is printed. Nothing is replaced.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
INTERIM = DATA / "interim"
EXTERNAL = DATA / "external"
OUTPUT = ROOT / "output"
RUNS = OUTPUT / "runs"
LOGS = ROOT / "logs"
SEED = 42


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def utc_stamp(t: dt.datetime | None = None) -> str:
    return (t or utc_now()).strftime("%Y%m%dT%H%M%SZ")


def utc_iso(t: dt.datetime | None = None) -> str:
    return (t or utc_now()).strftime("%Y-%m-%dT%H:%M:%SZ")


def rel(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _free_variant(dest: Path) -> Path:
    stamp = utc_stamp()
    candidate = dest.with_name(f"{dest.stem}.{stamp}{dest.suffix}")
    n = 1
    while candidate.exists():
        candidate = dest.with_name(f"{dest.stem}.{stamp}-{n}{dest.suffix}")
        n += 1
    return candidate


def place_file(tmp: Path, dest: Path, quiet: bool = False) -> Path:
    """Move a finished temporary file to ``dest`` without replacing anything.

    ``tmp`` must be on the same filesystem as ``dest``. ``os.link`` fails if
    the target exists, so a file appearing between the check and the link
    raises instead of being overwritten.
    """
    tmp, dest = Path(tmp), Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if sha256_file(dest) == sha256_file(tmp):
            tmp.unlink()
            if not quiet:
                print(f"UNCHANGED {rel(dest)}")
            return dest
        alt = _free_variant(dest)
        os.link(tmp, alt)
        tmp.unlink()
        print(f"NOTE {rel(dest)} already exists with different content; "
              f"new version written to {rel(alt)}")
        return alt
    os.link(tmp, dest)
    tmp.unlink()
    if not quiet:
        print(f"WROTE {rel(dest)}")
    return dest


def write_with(dest: Path, writer: Callable[[Path], None], quiet: bool = False) -> Path:
    """Call ``writer(tmp_path)`` then place the result with ``place_file``."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".tmp-", suffix=dest.suffix, dir=dest.parent)
    os.close(fd)
    tmp = Path(name)
    try:
        writer(tmp)
        return place_file(tmp, dest, quiet=quiet)
    finally:
        if tmp.exists():
            tmp.unlink()


def write_bytes(dest: Path, data: bytes, quiet: bool = False) -> Path:
    return write_with(dest, lambda p: p.write_bytes(data), quiet=quiet)


def write_text(dest: Path, text: str, quiet: bool = False) -> Path:
    return write_bytes(dest, text.encode("utf-8"), quiet=quiet)


def write_json(dest: Path, obj, quiet: bool = False) -> Path:
    text = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n"
    return write_text(dest, text, quiet=quiet)


def write_csv(dest: Path, df, quiet: bool = False) -> Path:
    return write_with(dest, lambda p: df.to_csv(p, index=False, lineterminator="\n"), quiet=quiet)


def write_rows_csv(dest: Path, rows: list[dict], fields: list[str], quiet: bool = False) -> Path:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in fields})
    return write_text(dest, buf.getvalue(), quiet=quiet)


def write_parquet(dest: Path, df, quiet: bool = False) -> Path:
    return write_with(dest, lambda p: df.to_parquet(p, index=False), quiet=quiet)


def save_figure(fig, stem: Path) -> list[Path]:
    """Save a matplotlib figure as PNG and PDF with fixed metadata."""
    stem = Path(stem)
    out = [
        write_with(stem.with_suffix(".png"),
                   lambda p: fig.savefig(p, format="png", dpi=200, metadata={"Software": None})),
        write_with(stem.with_suffix(".pdf"),
                   lambda p: fig.savefig(p, format="pdf",
                                         metadata={"Creator": None, "Producer": None,
                                                   "CreationDate": None})),
    ]
    return out


def git_state() -> dict:
    def run(*args):
        try:
            r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True)
            return r.stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None
    commit = run("rev-parse", "HEAD")
    status = run("status", "--porcelain", "--untracked-files=no")
    return {"commit": commit or "unknown",
            "dirty": None if status is None else bool(status)}


class Run:
    """One run of one stage: ``output/runs/<stage>/<UTC stamp>/`` plus ``run.json``."""

    def __init__(self, stage: str):
        self.stage = stage
        self.started = utc_now()
        base = RUNS / stage / utc_stamp(self.started)
        path, n = base, 1
        while path.exists():
            path = base.with_name(f"{base.name}-{n}")
            n += 1
        path.mkdir(parents=True)
        self.dir = path

    def finish(self, summary: dict) -> Path:
        finished = utc_now()
        record = {
            "stage": self.stage,
            "started_utc": utc_iso(self.started),
            "finished_utc": utc_iso(finished),
            "git": git_state(),
            "python": platform.python_version(),
            "argv": sys.argv[1:],
            "summary": summary,
        }
        out = write_json(self.dir / "run.json", record)
        LOGS.mkdir(parents=True, exist_ok=True)
        log = LOGS / "runs.csv"
        new = not log.exists()
        with open(log, "a", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            if new:
                w.writerow(["finished_utc", "stage", "run_dir", "git_commit", "git_dirty", "summary"])
            w.writerow([record["finished_utc"], self.stage, rel(self.dir), record["git"]["commit"],
                        record["git"]["dirty"], json.dumps(summary, sort_keys=True, default=str)])
        return out
