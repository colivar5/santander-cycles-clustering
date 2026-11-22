"""Apply the cleaning rules of notes/cleaning-rules.md (approved 2026-11-22).

R1 start time in 2025; R2 missing start or end station removed; R3 duration
empty, zero or negative removed; R4 no upper limit (long trips are a
features question); R5 round trips flagged, not removed; R6 duration
against start and end times checked, nothing removed; R7 rows identical in
every published column except the trip id kept once (lowest trip id);
R8 station id is the key, nothing merged, id/name conflicts listed.

    python src/clean.py

Reads ``data/interim/trips_loaded.parquet``. Writes
``data/interim/trips_clean.parquet``, ``data/interim/trips_excluded.parquet``
and, in ``output/runs/clean/<UTC>/``: ``waterfall.csv``,
``station_names.csv``, ``duration_gaps.csv``, ``run.json``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import INTERIM, Run, rel, sha256_file, write_csv, write_parquet  # noqa: E402

SOURCE = INTERIM / "trips_loaded.parquet"
CLEAN = INTERIM / "trips_clean.parquet"
EXCLUDED = INTERIM / "trips_excluded.parquet"

YEAR_FROM = pd.Timestamp("2025-01-01 00:00")
YEAR_TO = pd.Timestamp("2026-01-01 00:00")
CLOCK_CHANGES = [
    (pd.Timestamp("2025-03-30 01:00"), pd.Timestamp("2025-03-30 02:00"), -3600),
    (pd.Timestamp("2025-10-26 02:00"), pd.Timestamp("2025-10-26 01:00"), 3600),
]
GAP_LIMIT_S = 60
PUBLISHED = ["start_time", "start_station_id", "start_station_name", "end_time", "end_station_id",
             "end_station_name", "bike_id", "bike_model", "duration_text", "duration_ms"]


def read_loaded(path: Path = SOURCE) -> pd.DataFrame:
    return pq.read_table(path).to_pandas(types_mapper={pa.int64(): pd.Int64Dtype()}.get)


def apply_rules(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (kept trips, removed trips with their rule, waterfall)."""
    steps = [("loaded", len(df), 0)]
    removed = []

    def drop(frame, mask, rule):
        mask = mask.fillna(True).astype(bool)
        removed.append(frame[mask].assign(rule=rule))
        kept = frame[~mask]
        steps.append((rule, len(kept), int(mask.sum())))
        return kept

    df = drop(df, ~df["start_time"].between(YEAR_FROM, YEAR_TO, inclusive="left"), "R1_start_not_in_2025")
    df = drop(df, (df["start_station_id"] == "") | (df["end_station_id"] == ""), "R2_missing_station")
    df = drop(df, df["duration_ms"].isna() | (df["duration_ms"] <= 0), "R3_duration_not_positive")
    order = df.sort_values("trip_id", kind="stable")
    dup = order.duplicated(subset=PUBLISHED, keep="first").reindex(df.index)
    df = drop(df, dup, "R7_duplicate_of_lower_trip_id")
    df = df.assign(is_round_trip=df["start_station_id"] == df["end_station_id"])

    waterfall = pd.DataFrame(steps, columns=["step", "rows_left", "rows_removed"])
    excluded = pd.concat(removed, ignore_index=True)
    return df.reset_index(drop=True), excluded, waterfall


def duration_gaps(df: pd.DataFrame) -> pd.DataFrame:
    """R6: rows whose published duration and clock times differ by GAP_LIMIT_S or more."""
    clock = (df["end_time"] - df["start_time"]).dt.total_seconds()
    gap = df["duration_ms"].astype("float64") / 1000 - clock
    out = df.loc[gap.abs() >= GAP_LIMIT_S, ["trip_id", "start_time", "end_time", "duration_ms",
                                            "start_station_id", "end_station_id", "source_file"]].copy()
    out["gap_s"] = gap[out.index].round(3)
    across = pd.Series(False, index=out.index)
    for start_before, end_after, expected in CLOCK_CHANGES:
        spans = (out["start_time"] < start_before) & (out["end_time"] >= end_after)
        across |= spans & ((out["gap_s"] - expected).abs() < GAP_LIMIT_S)
    out["kind"] = across.map({True: "across_clock_change", False: "other"})
    return out.sort_values("trip_id").reset_index(drop=True)


def station_names(df: pd.DataFrame) -> pd.DataFrame:
    """R8: every (station id, name) pair with its departures and arrivals, and each id's label."""
    dep = df.groupby(["start_station_id", "start_station_name"]).size()
    arr = df.groupby(["end_station_id", "end_station_name"]).size()
    dep.index.names = arr.index.names = ["station_id", "station_name"]
    t = pd.concat({"departures": dep, "arrivals": arr}, axis=1).fillna(0).astype("int64").reset_index()
    t["trips"] = t["departures"] + t["arrivals"]
    t["names_for_id"] = t.groupby("station_id")["station_name"].transform("size")
    t["ids_for_name"] = t.groupby("station_name")["station_id"].transform("size")
    ranked = t.sort_values(["station_id", "trips", "station_name"], ascending=[True, False, True])
    label = ranked.drop_duplicates("station_id").set_index("station_id")["station_name"]
    t["label"] = t["station_id"].map(label)
    t["is_label"] = t["station_name"] == t["label"]
    return t.sort_values(["station_id", "trips", "station_name"], ascending=[True, False, True]).reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    if not SOURCE.exists():
        raise SystemExit(f"{rel(SOURCE)} not found; run the load stage first")
    run = Run("clean")
    source_sha = sha256_file(SOURCE)
    clean, excluded, waterfall = apply_rules(read_loaded())
    gaps = duration_gaps(clean)
    names = station_names(clean)

    out_clean = write_parquet(CLEAN, clean)
    out_excl = write_parquet(EXCLUDED, excluded)
    write_csv(run.dir / "waterfall.csv", waterfall)
    write_csv(run.dir / "station_names.csv", names)
    write_csv(run.dir / "duration_gaps.csv", gaps)

    ids = names.drop_duplicates("station_id")
    summary = {
        "input": rel(SOURCE), "input_sha256": source_sha,
        "waterfall": {r.step: {"rows_left": int(r.rows_left), "rows_removed": int(r.rows_removed)}
                      for r in waterfall.itertuples()},
        "trips_2025_clean": len(clean),
        "round_trips": int(clean["is_round_trip"].sum()),
        "duration_gaps": {k: int(v) for k, v in gaps["kind"].value_counts().sort_index().items()},
        "station_ids": int(names["station_id"].nunique()),
        "station_ids_with_more_than_one_name": int((ids["names_for_id"] > 1).sum()),
        "station_names_with_more_than_one_id": int(names.loc[names["ids_for_name"] > 1, "station_name"].nunique()),
        "outputs": {rel(out_clean): sha256_file(out_clean), rel(out_excl): sha256_file(out_excl)},
    }
    run.finish(summary)
    for k, v in summary.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
