"""Load the downloaded trip files into one typed Parquet file, keeping every row.

Reads every file listed in ``data/raw/MANIFEST.csv`` (after checking its
SHA-256 against the manifest), every field as text, and maps columns by
header name: the 11 column names are the same in every file but their order
changes between files. Nothing is dropped or corrected here; that is the
cleaning stage, under ``notes/cleaning-rules.md``.

Types: trip id and duration in ms as integers, start and end times as
timestamps exactly as published (minute resolution, London clock time, no
time zone attached), everything else as text, station numbers with their
leading zeros. A value that does not parse becomes null and is counted, and
its row is written with the original text to ``parse_failures.csv`` in the
run folder.

    python src/load.py

Writes ``data/interim/trips_loaded.parquet`` and, in
``output/runs/load/<UTC>/``: ``per_file.csv``, ``header_layouts.csv``,
``daily_counts.csv``, ``cross_file_ids.csv``, ``parse_failures.csv``,
``run.json``.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import INTERIM, RAW, Run, rel, sha256_file, write_csv, write_with  # noqa: E402

MANIFEST = RAW / "MANIFEST.csv"
SOURCE_DIR = RAW / "tfl-usage-stats"
OUT = INTERIM / "trips_loaded.parquet"

COLUMNS = {
    "Number": "trip_id",
    "Start date": "start_time",
    "Start station number": "start_station_id",
    "Start station": "start_station_name",
    "End date": "end_time",
    "End station number": "end_station_id",
    "End station": "end_station_name",
    "Bike number": "bike_id",
    "Bike model": "bike_model",
    "Total duration": "duration_text",
    "Total duration (ms)": "duration_ms",
}
SCHEMA = pa.schema([
    ("trip_id", pa.int64()),
    ("start_time", pa.timestamp("s")),
    ("start_station_id", pa.string()),
    ("start_station_name", pa.string()),
    ("end_time", pa.timestamp("s")),
    ("end_station_id", pa.string()),
    ("end_station_name", pa.string()),
    ("bike_id", pa.string()),
    ("bike_model", pa.string()),
    ("duration_text", pa.string()),
    ("duration_ms", pa.int64()),
    ("source_file", pa.int16()),
])
TIME_FORMAT = "%Y-%m-%d %H:%M"
DIGITS = re.compile(r"^\d+$")
FILE_NUMBER = re.compile(r"^(\d+)JourneyData")


def read_header(path: Path) -> list[str]:
    with open(path, newline="", encoding="utf-8") as fh:
        return next(csv.reader(fh))


def count_data_lines(path: Path) -> int:
    n, last = 0, b"\n"
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 22), b""):
            n += block.count(b"\n")
            last = block[-1:]
    return n - 1 + (last != b"\n")


def read_text_table(path: Path) -> pd.DataFrame:
    header = read_header(path)
    if sorted(header) != sorted(COLUMNS) or len(header) != len(set(header)):
        raise ValueError(f"{path.name}: unexpected header {header}")
    table = pacsv.read_csv(
        path,
        read_options=pacsv.ReadOptions(use_threads=True),
        parse_options=pacsv.ParseOptions(newlines_in_values=False),
        convert_options=pacsv.ConvertOptions(
            column_types={c: pa.string() for c in header},
            strings_can_be_null=False, quoted_strings_can_be_null=False))
    df = table.to_pandas()
    return df.rename(columns=COLUMNS)[list(COLUMNS.values())]


def parse_times(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, format=TIME_FORMAT, errors="coerce").astype("datetime64[s]")


def parse_int(s: pd.Series) -> pd.Series:
    ok = s.str.fullmatch(DIGITS.pattern)
    out = pd.Series(pd.NA, index=s.index, dtype="Int64")
    out[ok] = s[ok].astype("int64")
    return out


def type_frame(text: pd.DataFrame, number: int) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Typed copy of ``text`` (all-text columns), the rows that failed to parse, and counts."""
    typed = text.copy()
    failed = pd.Series(False, index=text.index)
    counts = {}
    for col, parse in (("trip_id", parse_int), ("duration_ms", parse_int),
                       ("start_time", parse_times), ("end_time", parse_times)):
        typed[col] = parse(text[col])
        bad = typed[col].isna() & (text[col] != "")
        counts[f"empty_{col}"] = int((text[col] == "").sum())
        counts[f"unparsed_{col}"] = int(bad.sum())
        failed |= bad
    for col in ("start_station_id", "start_station_name", "end_station_id", "end_station_name",
                "bike_id", "bike_model", "duration_text"):
        counts[f"empty_{col}"] = int((text[col] == "").sum())
    if typed["trip_id"].isna().any():
        raise ValueError(f"file {number}: {int(typed['trip_id'].isna().sum())} rows without a usable trip id")
    typed["trip_id"] = typed["trip_id"].astype("int64")
    typed["source_file"] = np.int16(number)
    failures = text[failed].assign(source_file=number)
    return typed, failures, counts


def manifest_rows() -> list[dict]:
    with open(MANIFEST, newline="") as fh:
        rows = list(csv.DictReader(fh))
    missing = [r["file"] for r in rows if r["status"] != "present"]
    if missing:
        raise SystemExit(f"manifest lists files not present: {missing}; run the download stage first")
    return sorted(rows, key=lambda r: int(FILE_NUMBER.match(r["file"]).group(1)))


def main(argv: list[str] | None = None) -> int:
    rows = manifest_rows()
    run = Run("load")
    per_file, layouts, daily, id_parts, failures = [], {}, [], [], []

    def write_all(tmp: Path) -> None:
        with pq.ParquetWriter(tmp, SCHEMA) as writer:
            for r in rows:
                path = SOURCE_DIR / r["file"]
                number = int(FILE_NUMBER.match(r["file"]).group(1))
                sha = sha256_file(path)
                if sha != r["sha256"]:
                    raise SystemExit(f"{r['file']}: SHA-256 {sha} differs from the manifest {r['sha256']}")
                header = read_header(path)
                layout = layouts.setdefault(tuple(header), len(layouts) + 1)
                text = read_text_table(path)
                lines = count_data_lines(path)
                if len(text) != lines:
                    raise SystemExit(f"{r['file']}: parsed {len(text)} rows but the file has {lines} data lines")
                typed, bad, counts = type_frame(text, number)
                failures.append(bad)
                dup_in_file = int(typed["trip_id"].duplicated().sum())
                per_file.append({
                    "file": r["file"], "number": number, "role": r["role"], "header_layout": layout,
                    "rows": len(typed), "trip_id_min": int(typed["trip_id"].min()),
                    "trip_id_max": int(typed["trip_id"].max()), "duplicate_trip_ids_in_file": dup_in_file,
                    "start_time_min": typed["start_time"].min(), "start_time_max": typed["start_time"].max(),
                    "end_time_min": typed["end_time"].min(), "end_time_max": typed["end_time"].max(),
                    **counts})
                days = typed["start_time"].dt.date.value_counts(dropna=False).sort_index()
                daily.extend({"source_file": number, "start_date": d, "trips": int(n)} for d, n in days.items())
                id_parts.append(pd.DataFrame({"trip_id": typed["trip_id"].to_numpy(),
                                              "source_file": typed["source_file"].to_numpy()}))
                writer.write_table(pa.Table.from_pandas(typed, schema=SCHEMA, preserve_index=False))
                print(f"read {r['file']}: {len(typed):,} rows, layout {layout}, "
                      f"{len(bad)} rows with unparsed values")

    out = write_with(OUT, write_all)

    ids = pd.concat(id_parts, ignore_index=True)
    multi = ids[ids.duplicated("trip_id", keep=False)]
    cross = (multi.groupby("trip_id")["source_file"].agg(lambda s: "+".join(map(str, sorted(s))))
             .rename("files").reset_index())
    cross_summary = cross["files"].value_counts().rename_axis("files").reset_index(name="trip_ids")
    identical = 0
    if len(cross):
        dup = pq.read_table(out, filters=[("trip_id", "in", cross["trip_id"].tolist())]).to_pandas()
        fields = [c for c in dup.columns if c != "source_file"]
        identical = int(dup.groupby("trip_id")[fields].nunique(dropna=False).le(1).all(axis=1).sum())

    layout_rows = [{"header_layout": n, "columns": " | ".join(h),
                    "files": " ".join(str(p["number"]) for p in per_file if p["header_layout"] == n)}
                   for h, n in layouts.items()]
    write_csv(run.dir / "per_file.csv", pd.DataFrame(per_file))
    write_csv(run.dir / "header_layouts.csv", pd.DataFrame(layout_rows))
    write_csv(run.dir / "daily_counts.csv", pd.DataFrame(daily))
    write_csv(run.dir / "cross_file_ids.csv", cross_summary)
    write_csv(run.dir / "parse_failures.csv",
              pd.concat(failures, ignore_index=True) if failures else pd.DataFrame())

    pf = pd.DataFrame(per_file)
    summary = {
        "files": len(per_file),
        "rows": int(pf["rows"].sum()),
        "rows_by_role": {k: int(v) for k, v in pf.groupby("role")["rows"].sum().items()},
        "header_layouts": len(layouts),
        "duplicate_trip_ids_within_files": int(pf["duplicate_trip_ids_in_file"].sum()),
        "trip_ids_in_more_than_one_file": int(len(cross)),
        "of_which_identical_in_every_field": identical,
        "rows_with_unparsed_values": int(sum(len(f) for f in failures)),
        "output": rel(out),
        "output_sha256": sha256_file(out),
    }
    run.finish(summary)
    for k, v in summary.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
