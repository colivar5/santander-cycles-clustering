"""Fetch TfL's BikePoint station list and match it to the station ids of the trips.

Brief §2.1 (optional): station coordinates from TfL's BikePoint feed. The
feed describes the stations as they are when it is fetched, so every fetch
is kept as its own file, exactly as received, and recorded in
``data/external/SOURCES.csv``.

    python src/bikepoint.py                 # fetch now, save, parse, match
    python src/bikepoint.py --file PATH     # parse and match a saved snapshot, no fetch

``--file`` refuses a snapshot that ``SOURCES.csv`` does not record, or whose
bytes no longer match the recorded SHA-256. ``run_all.py`` uses ``--file``
on the committed snapshot and never fetches.

Writes ``data/external/bikepoint/BikePoint_<UTC>.json`` and a row in
``data/external/SOURCES.csv`` (fetch only), ``data/interim/bikepoint_stations.csv``
and, in ``output/runs/bikepoint/<UTC>/``: ``match.csv``, ``run.json``.
Matching needs ``data/interim/trips_clean.parquet`` (clean stage); without
it the match is skipped.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import EXTERNAL, INTERIM, Run, rel, sha256_file, utc_iso, utc_stamp, write_bytes, write_csv  # noqa: E402

URL = "https://api.tfl.gov.uk/BikePoint"
USER_AGENT = "santander-cycles-clustering/0.1 (course project)"
SNAPSHOTS = EXTERNAL / "bikepoint"
SOURCES = EXTERNAL / "SOURCES.csv"
SOURCES_FIELDS = ["file", "url", "retrieved_at_utc", "size_bytes", "sha256", "used_for"]
STATIONS = INTERIM / "bikepoint_stations.csv"
TRIPS = INTERIM / "trips_clean.parquet"
TERMINAL_KEY = "TerminalName"


def fetch(attempts: int = 4) -> bytes:
    req = urllib.request.Request(URL, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
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


def record_source(path: Path, retrieved: str) -> None:
    new = not SOURCES.exists()
    SOURCES.parent.mkdir(parents=True, exist_ok=True)
    with open(SOURCES, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SOURCES_FIELDS, lineterminator="\n")
        if new:
            w.writeheader()
        w.writerow({"file": rel(path), "url": URL, "retrieved_at_utc": retrieved,
                    "size_bytes": path.stat().st_size, "sha256": sha256_file(path),
                    "used_for": "station names and coordinates (brief §2.1, optional)"})


def check_recorded(path: Path, sources: Path = SOURCES) -> None:
    """A saved snapshot is read only if SOURCES.csv records it and its bytes still have the recorded SHA-256."""
    rows = []
    if sources.exists():
        with open(sources, newline="") as f:
            rows = [r for r in csv.DictReader(f) if r["file"] == rel(path)]
    if not rows:
        raise SystemExit(f"{rel(path)} is not recorded in {rel(sources)}")
    if sha256_file(path) != rows[-1]["sha256"]:
        raise SystemExit(f"{rel(path)} does not match the SHA-256 recorded in {rel(sources)}")


def parse(raw: bytes) -> pd.DataFrame:
    """One row per BikePoint place: id, name, lat, lon, then every additional property as a column."""
    places = json.loads(raw)
    if not isinstance(places, list) or not places:
        raise ValueError("BikePoint response is not a non-empty list")
    rows = []
    for p in places:
        missing = [k for k in ("id", "commonName", "lat", "lon", "additionalProperties") if k not in p]
        if missing:
            raise ValueError(f"place {p.get('id')} lacks {missing}")
        row = {"bikepoint_id": p["id"], "name": p["commonName"], "lat": p["lat"], "lon": p["lon"]}
        for prop in p["additionalProperties"]:
            if prop["key"] in row:
                raise ValueError(f"place {p['id']}: property {prop['key']} given twice")
            row[prop["key"]] = prop["value"]
        rows.append(row)
    df = pd.DataFrame(rows)
    if TERMINAL_KEY not in df.columns:
        raise ValueError(f"no '{TERMINAL_KEY}' property; keys seen: {sorted(df.columns)}")
    if df[TERMINAL_KEY].isna().any() or df[TERMINAL_KEY].duplicated().any():
        raise ValueError(f"'{TERMINAL_KEY}' is missing or repeated for some places")
    return df.sort_values("bikepoint_id", kind="stable").reset_index(drop=True)


def trip_stations(path: Path = TRIPS) -> pd.DataFrame:
    t = pq.read_table(path, columns=["start_station_id", "end_station_id"]).to_pandas()
    counts = pd.concat([t["start_station_id"], t["end_station_id"]]).value_counts()
    return counts.rename_axis("station_id").reset_index(name="trip_ends")


def match(stations: pd.DataFrame, bp: pd.DataFrame) -> pd.DataFrame:
    """Each trip station id against BikePoint's terminal names, exactly as both are written."""
    by_terminal = bp.set_index(TERMINAL_KEY)[["bikepoint_id", "name", "lat", "lon"]]
    out = stations.merge(by_terminal, how="left", left_on="station_id", right_index=True)
    out["in_bikepoint"] = out["bikepoint_id"].notna()
    return out.sort_values("station_id").reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path, help="parse this saved snapshot instead of fetching")
    args = ap.parse_args(argv)

    run = Run("bikepoint")
    if args.file:
        snapshot = args.file
        check_recorded(snapshot)
        raw = snapshot.read_bytes()
    else:
        retrieved = utc_iso()
        raw = fetch()
        snapshot = write_bytes(SNAPSHOTS / f"BikePoint_{utc_stamp()}.json", raw)
        record_source(snapshot, retrieved)
    bp = parse(raw)
    write_csv(STATIONS, bp)

    summary = {"snapshot": rel(snapshot), "snapshot_sha256": sha256_file(snapshot), "places": len(bp),
               "property_keys": sorted(c for c in bp.columns if c not in ("bikepoint_id", "name", "lat", "lon"))}
    if TRIPS.exists():
        m = match(trip_stations(), bp)
        write_csv(run.dir / "match.csv", m)
        stripped = set(bp[TERMINAL_KEY].astype(str).str.lstrip("0"))
        unmatched = m.loc[~m["in_bikepoint"], "station_id"].tolist()
        summary.update({
            "trip_station_ids": len(m),
            "trip_station_ids_in_bikepoint": int(m["in_bikepoint"].sum()),
            "trip_station_ids_not_in_bikepoint": unmatched if len(unmatched) <= 40
            else f"{len(unmatched)} ids; see match.csv",
            "would_match_ignoring_leading_zeros": int(m["station_id"].str.lstrip("0").isin(stripped).sum()),
            "bikepoint_places_without_trips": int((~bp[TERMINAL_KEY].isin(m["station_id"])).sum()),
        })
    else:
        print(f"NOTE {rel(TRIPS)} not found; match skipped")
    run.finish(summary)
    for k, v in summary.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
