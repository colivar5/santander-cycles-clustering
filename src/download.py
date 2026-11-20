"""Download the TfL Santander Cycles trip files that cover 2025.

Selection rule (written in notes/data-selection.md before downloading):
every ``<n>JourneyDataExtract<start>-<end>.csv`` file in ``usage-stats/``
whose date range intersects 2025-01-01..2025-12-31, plus the file just
before and just after them by number, kept only to check the year
boundaries. Files are stored exactly as downloaded in
``data/raw/tfl-usage-stats/``; ``data/raw/MANIFEST.csv`` records URL, S3
key, size, S3's stored CRC64-NVME checksum, SHA-256 and download time. Every
download is checked against its size and S3's full-file CRC64-NVME checksum
(the S3 ETags of these files are multipart and cannot be recomputed). A file
already on disk that matches is not downloaded again.

    python src/download.py             # download what is missing, write manifest
    python src/download.py --dry-run   # list and check the selection, write nothing
    python src/download.py --only 411  # restrict downloads to these file numbers
"""
from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import hashlib
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from awscrt import checksums  # noqa: E402
from common import RAW, Run, place_file, rel, sha256_file, utc_iso, write_bytes, write_rows_csv  # noqa: E402

BUCKET_URL = "https://s3-eu-west-1.amazonaws.com/cycling.data.tfl.gov.uk/"
PREFIX = "usage-stats/"
DEST = RAW / "tfl-usage-stats"
MANIFEST = RAW / "MANIFEST.csv"
YEAR_START = dt.date(2025, 1, 1)
YEAR_END = dt.date(2025, 12, 31)
USER_AGENT = "santander-cycles-clustering/0.1 (course project)"
CHECKSUM_HEADER = {"x-amz-checksum-mode": "ENABLED"}
S3_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
NAME_RE = re.compile(r"^(\d+)JourneyDataExtract(\d{2}[A-Za-z]{3}\d{4})-(\d{2}[A-Za-z]{3}\d{4})\.csv$")
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
MANIFEST_FIELDS = ["file", "role", "url", "s3_key", "s3_last_modified", "s3_etag",
                   "size_bytes", "s3_crc64nvme", "checksum_check", "sha256", "downloaded_at_utc", "status"]


@dataclass(frozen=True)
class TripFile:
    key: str
    number: int
    start: dt.date
    end: dt.date
    size: int
    etag: str
    last_modified: str

    @property
    def name(self) -> str:
        return self.key[len(PREFIX):]

    @property
    def url(self) -> str:
        return BUCKET_URL + urllib.parse.quote(self.key)


def parse_day(s: str) -> dt.date:
    return dt.date(int(s[5:9]), MONTHS[s[2:5].lower()], int(s[0:2]))


def http_get(url: str, attempts: int = 4) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except OSError as e:
            if i == attempts - 1:
                raise
            wait = 2 ** (i + 1)
            print(f"retry {i + 1} after error: {e}; waiting {wait}s")
            time.sleep(wait)
    raise AssertionError("unreachable")


def fetch_listing() -> list[bytes]:
    pages, token = [], None
    while True:
        q = {"list-type": "2", "prefix": PREFIX}
        if token:
            q["continuation-token"] = token
        body = http_get(BUCKET_URL + "?" + urllib.parse.urlencode(q))
        pages.append(body)
        root = ET.fromstring(body)
        if root.findtext("s3:IsTruncated", namespaces=S3_NS) != "true":
            return pages
        token = root.findtext("s3:NextContinuationToken", namespaces=S3_NS)


def parse_listing(pages: list[bytes]) -> list[TripFile]:
    files = []
    for body in pages:
        for c in ET.fromstring(body).findall("s3:Contents", S3_NS):
            key = c.findtext("s3:Key", namespaces=S3_NS)
            m = NAME_RE.match(key[len(PREFIX):]) if key.startswith(PREFIX) else None
            if not m:
                continue
            files.append(TripFile(
                key=key, number=int(m.group(1)), start=parse_day(m.group(2)), end=parse_day(m.group(3)),
                size=int(c.findtext("s3:Size", namespaces=S3_NS)),
                etag=c.findtext("s3:ETag", namespaces=S3_NS).strip('"'),
                last_modified=c.findtext("s3:LastModified", namespaces=S3_NS)))
    return sorted(files, key=lambda f: f.number)


def select(files: list[TripFile]) -> tuple[list[TripFile], list[TripFile]]:
    year = [f for f in files if f.start <= YEAR_END and f.end >= YEAR_START]
    if not year:
        raise SystemExit("no file in the listing covers 2025")
    lo, hi = year[0].number, year[-1].number
    numbers = [f.number for f in year]
    assert numbers == list(range(lo, hi + 1)), f"2025 file numbers are not contiguous: {numbers}"
    by_number = {f.number: f for f in files}
    boundary = [by_number[n] for n in (lo - 1, hi + 1) if n in by_number]
    return year, boundary


def coverage(year: list[TripFile]) -> dict:
    days: dict[dt.date, list[int]] = {}
    for f in year:
        d = max(f.start, YEAR_START)
        while d <= min(f.end, YEAR_END):
            days.setdefault(d, []).append(f.number)
            d += dt.timedelta(days=1)
    n_days = (YEAR_END - YEAR_START).days + 1
    missing = [str(YEAR_START + dt.timedelta(days=i)) for i in range(n_days)
               if YEAR_START + dt.timedelta(days=i) not in days]
    overlaps = {str(d): nums for d, nums in sorted(days.items()) if len(nums) > 1}
    return {"days_covered": len(days), "days_in_year": n_days, "missing_days": missing,
            "overlapping_days": overlaps}


def crc64nvme_file(path: Path) -> str:
    """Full-file CRC64-NVME, base64 of the 8 big-endian bytes, as S3 reports it."""
    crc = 0
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            crc = checksums.crc64nvme(block, crc)
    return base64.b64encode(crc.to_bytes(8, "big")).decode()


def s3_checksum(f: TripFile, attempts: int = 4) -> str:
    """The CRC64-NVME checksum S3 stores for ``f`` ('' if S3 has none)."""
    req = urllib.request.Request(f.url, method="HEAD", headers={"User-Agent": USER_AGENT, **CHECKSUM_HEADER})
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.headers.get("x-amz-checksum-crc64nvme", "")
        except OSError as e:
            if i == attempts - 1:
                raise
            time.sleep(2 ** (i + 1))
            print(f"retry {i + 1} for HEAD {f.name} after error: {e}")
    raise AssertionError("unreachable")


def download(f: TripFile, attempts: int = 4) -> tuple[Path, str, str]:
    """Stream ``f`` to a temporary file next to its destination; check size and S3 checksum."""
    DEST.mkdir(parents=True, exist_ok=True)
    tmp = DEST / f".part-{f.name}"
    req = urllib.request.Request(f.url, headers={"User-Agent": USER_AGENT, **CHECKSUM_HEADER})
    for i in range(attempts):
        sha, crc, size = hashlib.sha256(), 0, 0
        try:
            with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as out:
                expected = r.headers.get("x-amz-checksum-crc64nvme", "")
                for block in iter(lambda: r.read(1 << 20), b""):
                    out.write(block)
                    sha.update(block)
                    crc = checksums.crc64nvme(block, crc)
                    size += len(block)
            break
        except OSError as e:
            if tmp.exists():
                tmp.unlink()
            if i == attempts - 1:
                raise
            wait = 2 ** (i + 1)
            print(f"retry {i + 1} for {f.name} after error: {e}; waiting {wait}s")
            time.sleep(wait)
    if size != f.size:
        tmp.unlink()
        raise RuntimeError(f"{f.name}: got {size} bytes, listing says {f.size}")
    got = base64.b64encode(crc.to_bytes(8, "big")).decode()
    if expected and got != expected:
        tmp.unlink()
        raise RuntimeError(f"{f.name}: CRC64-NVME {got} does not match S3 checksum {expected}")
    if not expected:
        print(f"NOTE {f.name}: S3 has no stored checksum; only the size was checked")
    return tmp, sha.hexdigest(), expected


def previous_download_times() -> dict[str, str]:
    seen: dict[str, str] = {}
    for path in sorted(RAW.glob("MANIFEST*.csv")):
        with open(path, newline="") as fh:
            for row in csv.DictReader(fh):
                if row.get("sha256") and row.get("downloaded_at_utc"):
                    seen.setdefault(row["sha256"], row["downloaded_at_utc"])
    return seen


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="list and check the selection, write nothing")
    ap.add_argument("--only", type=int, nargs="+", metavar="N", help="download only these file numbers")
    args = ap.parse_args(argv)

    pages = fetch_listing()
    files = parse_listing(pages)
    year, boundary = select(files)
    cov = coverage(year)
    print(f"listing: {len(files)} trip files; 2025: {len(year)} files "
          f"({year[0].name} .. {year[-1].name}); boundary checks: {[f.name for f in boundary]}")
    print(f"days of 2025 covered: {cov['days_covered']}/{cov['days_in_year']}; "
          f"days in more than one file: {cov['overlapping_days']}")
    assert not cov["missing_days"], f"days of 2025 not covered by any file: {cov['missing_days']}"
    selected = [(f, "year_2025") for f in year] + [(f, "boundary_check") for f in boundary]
    total = sum(f.size for f, _ in selected)
    print(f"selected: {len(selected)} files, {total / 1e6:.1f} MB")
    if args.dry_run:
        for f, role in selected:
            print(f"  {f.name:55s} {f.size / 1e6:7.1f} MB  {role}")
        return 0

    run = Run("download")
    for i, body in enumerate(pages, start=1):
        write_bytes(RAW / ("usage-stats-listing.xml" if len(pages) == 1 else f"usage-stats-listing-p{i}.xml"), body)
    known = previous_download_times()
    rows, counts = [], {"downloaded": 0, "already_present": 0, "absent": 0, "new_version": 0}
    for f, role in selected:
        dest = DEST / f.name
        row = {"file": f.name, "role": role, "url": f.url, "s3_key": f.key,
               "s3_last_modified": f.last_modified, "s3_etag": f.etag, "size_bytes": f.size}
        present_ok = False
        if dest.exists() and dest.stat().st_size == f.size:
            expected = s3_checksum(f)
            if expected and crc64nvme_file(dest) == expected:
                sha = sha256_file(dest)
                present_ok = True
                row.update(sha256=sha, s3_crc64nvme=expected, checksum_check="match",
                           downloaded_at_utc=known.get(sha, ""), status="present")
                counts["already_present"] += 1
                print(f"present  {f.name} (S3 checksum matches)")
        wanted = args.only is None or f.number in args.only
        if not present_ok and wanted:
            started = utc_iso()
            print(f"download {f.name} ({f.size / 1e6:.1f} MB)")
            tmp, sha, expected = download(f)
            placed = place_file(tmp, dest)
            new = placed != dest
            row.update(file=placed.name, sha256=sha, s3_crc64nvme=expected,
                       checksum_check="match" if expected else "size only",
                       downloaded_at_utc=started, status="new_version" if new else "present")
            counts["new_version" if new else "downloaded"] += 1
        elif not present_ok:
            row.update(status="absent")
            counts["absent"] += 1
        rows.append(row)
    write_rows_csv(MANIFEST, rows, MANIFEST_FIELDS)
    summary = {**counts, "files_selected": len(selected), "bytes_selected": total,
               "coverage": {k: v for k, v in cov.items() if k != "missing_days"},
               "manifest": rel(MANIFEST)}
    run.finish(summary)
    print(f"done: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
