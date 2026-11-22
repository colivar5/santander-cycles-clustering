"""Apply the cleaning rules of notes/cleaning-rules.md (approved 2026-11-22, R9 and R10 added the same day).

R1 start time in 2025; R2 missing start or end station removed; R3 duration
empty, zero or negative removed; R4 no upper limit (long trips are a
features question); R5 round trips flagged, not removed; R6 duration
against start and end times checked, nothing removed; R7 rows identical in
every published column except the trip id kept once (lowest trip id);
R8 station id is the key, id/name conflicts listed; R9 the 15 `_OLD` ids
merged into their 6-digit ids, published ids kept; R10 trips starting or
ending at a mechanical workshop removed.

    python src/clean.py

Reads ``data/interim/trips_loaded.parquet``. Writes
``data/interim/trips_clean.parquet``, ``data/interim/trips_excluded.parquet``
and, in ``output/runs/clean/<UTC>/``: ``waterfall.csv``,
``station_names.csv``, ``station_merges.csv``, ``duration_gaps.csv``,
``run.json``.
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
OLD_IDS = frozenset({
    "001059444", "001085444", "0011274444", "001190444", "001219444", "200025444", "200083444", "200134444",
    "200136444", "200141444", "2001454444", "200191444", "200230444", "300032444", "300241444",
})
WORKSHOP_TEXT = "Mechanical Workshop"
WORKSHOP_IDS = frozenset({"010626", "022168"})
PUBLISHED = ["start_time", "start_station_id", "start_station_name", "end_time", "end_station_id",
             "end_station_name", "bike_id", "bike_model", "duration_text", "duration_ms"]


def read_loaded(path: Path = SOURCE) -> pd.DataFrame:
    return pq.read_table(path).to_pandas(types_mapper={pa.int64(): pd.Int64Dtype()}.get)


def ends(df: pd.DataFrame) -> pd.DataFrame:
    """Every trip start and end as one row: station id and name."""
    cols = ["station_id", "station_name"]
    return pd.concat([df[["start_station_id", "start_station_name"]].set_axis(cols, axis=1),
                      df[["end_station_id", "end_station_name"]].set_axis(cols, axis=1)], ignore_index=True)


def old_id_merges(df: pd.DataFrame) -> dict[str, str]:
    """R9: long id -> 6-digit id, for ids that are a 6-digit id plus only 4s and whose every name is its label + _OLD."""
    e = ends(df)
    names = e.groupby("station_id")["station_name"].agg(set)
    labels = station_names(df).drop_duplicates("station_id").set_index("station_id")["label"]
    out = {}
    for sid, nm in names.items():
        base = sid[:6]
        if len(sid) > 6 and set(sid[6:]) == {"4"} and base in labels.index and nm == {labels[base] + "_OLD"}:
            out[sid] = base
    return out


def workshop_ids(df: pd.DataFrame) -> set[str]:
    """R10: ids that carry a name containing WORKSHOP_TEXT."""
    e = ends(df)
    return set(e.loc[e["station_name"].str.contains(WORKSHOP_TEXT, regex=False), "station_id"])


def apply_rules(df: pd.DataFrame, old_ids: frozenset = OLD_IDS, workshops: frozenset = WORKSHOP_IDS
                ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (kept trips, removed trips with their rule, waterfall, R9 merges).

    ``old_ids`` and ``workshops`` are the ids R9 and R10 must find; the run stops if they find others.
    """
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

    found = old_id_merges(df)
    if set(found) != set(old_ids):
        raise SystemExit(f"R9 found {sorted(found)}, expected {sorted(old_ids)}")
    merges = pd.DataFrame({"published_id": list(found), "merged_into": list(found.values())})
    merges["departures"] = merges["published_id"].map(df["start_station_id"].value_counts()).fillna(0).astype("int64")
    merges["arrivals"] = merges["published_id"].map(df["end_station_id"].value_counts()).fillna(0).astype("int64")
    merges = merges.sort_values("published_id").reset_index(drop=True)
    df = df.assign(start_station_id_published=df["start_station_id"], end_station_id_published=df["end_station_id"],
                   start_station_id=df["start_station_id"].map(lambda x: found.get(x, x)),
                   end_station_id=df["end_station_id"].map(lambda x: found.get(x, x)))
    steps.append(("R9_merge_old_ids", len(df), 0))

    ws = workshop_ids(df)
    if ws != set(workshops):
        raise SystemExit(f"R10 found {sorted(ws)}, expected {sorted(workshops)}")
    df = drop(df, df["start_station_id"].isin(ws) | df["end_station_id"].isin(ws), "R10_workshop")
    df = df.assign(is_round_trip=df["start_station_id"] == df["end_station_id"])

    waterfall = pd.DataFrame(steps, columns=["step", "rows_left", "rows_removed"])
    excluded = pd.concat(removed, ignore_index=True)
    return df.reset_index(drop=True), excluded, waterfall, merges


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
    clean, excluded, waterfall, merges = apply_rules(read_loaded())
    gaps = duration_gaps(clean)
    names = station_names(clean)

    out_clean = write_parquet(CLEAN, clean)
    out_excl = write_parquet(EXCLUDED, excluded)
    write_csv(run.dir / "waterfall.csv", waterfall)
    write_csv(run.dir / "station_names.csv", names)
    write_csv(run.dir / "station_merges.csv", merges)
    write_csv(run.dir / "duration_gaps.csv", gaps)

    ids = names.drop_duplicates("station_id")
    summary = {
        "input": rel(SOURCE), "input_sha256": source_sha,
        "waterfall": {r.step: {"rows_left": int(r.rows_left), "rows_removed": int(r.rows_removed)}
                      for r in waterfall.itertuples()},
        "trips_2025_clean": len(clean),
        "round_trips": int(clean["is_round_trip"].sum()),
        "r9_ids_merged": len(merges),
        "r9_trip_ends_moved": int(merges["departures"].sum() + merges["arrivals"].sum()),
        "r9_trips_now_round_trips": int((clean["is_round_trip"]
                                         & (clean["start_station_id_published"] != clean["end_station_id_published"])).sum()),
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
