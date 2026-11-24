"""Count, for every pair of stations, in how many SBM fits they share a block (D26 (b)).

Reads one main run of ``src/sbm.py`` and the fits it saved. Uses the fit set
of the model G4 kept (``main_model`` in the run's ``run.json``) and one level,
level 2 by default (D25). Before counting, the kept fit read from the saved
files is checked against the run's ``blocks.csv``.

    python src/sbm_coassign.py --run output/runs/sbm/<UTC>
    python src/sbm_coassign.py --run output/runs/sbm/<UTC> --level 3

Writes in ``output/runs/sbm_coassign/<UTC>/``: ``coassignment_level<L>.csv``
(``station_a``, ``station_b``, ``fits_together``; one row per pair together in
at least one fit, ``station_a < station_b``), ``run.json`` with how many pairs
are together in 1, 2, ... of the fits; a row in ``logs/runs.csv``.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, Run, rel, sha256_file, write_rows_csv  # noqa: E402
from sbm_compare import blocks_from_csv, load_levels  # noqa: E402

FIELDS = ["station_a", "station_b", "fits_together"]


def stations_from_csv(path: Path, fit: str) -> list[str]:
    with open(path, newline="") as f:
        return [r["station_id"] for r in csv.DictReader(f) if r["fit"] == fit and r["level"] == "0"]


def coassignment(stations: list[str], partitions: list[np.ndarray]) -> Counter:
    """For each pair of stations (in sorted id order), the number of partitions putting them in one block."""
    counts: Counter = Counter()
    for b in partitions:
        groups: dict[int, list[str]] = {}
        for s, block in zip(stations, b):
            groups.setdefault(int(block), []).append(s)
        for members in groups.values():
            counts.update(combinations(sorted(members), 2))
    return counts


def collect(run_dir: Path, saved_dir: Path, level: int) -> tuple[list[str], list[np.ndarray], dict]:
    summary = json.loads((run_dir / "run.json").read_text())["summary"]
    if summary.get("mode") != "main":
        raise SystemExit(f"{rel(run_dir)} is not a main SBM run")
    fit = summary["main_model"]
    kept_seed = summary["kept"][fit]["seed"]
    stations = stations_from_csv(run_dir / "blocks.csv", fit)
    in_csv = blocks_from_csv(run_dir / "blocks.csv")[fit]
    partitions = []
    for seed in summary["seeds"]:
        levels = load_levels(saved_dir / f"{fit}_seed{seed}.json")
        if seed == kept_seed and (len(levels) != len(in_csv)
                                  or not all(np.array_equal(a, b) for a, b in zip(levels, in_csv))):
            raise SystemExit(f"saved fit {fit} seed {seed} differs from {rel(run_dir / 'blocks.csv')}")
        if len(levels) <= level:
            raise SystemExit(f"fit {fit} seed {seed} has no level {level}")
        if len(levels[level]) != len(stations):
            raise SystemExit(f"fit {fit} seed {seed} has {len(levels[level])} stations, blocks.csv {len(stations)}")
        partitions.append(levels[level])
    return stations, partitions, {"fit": fit, "kept_seed": kept_seed, "seeds": summary["seeds"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path, required=True, help="a main run folder of src/sbm.py")
    ap.add_argument("--level", type=int, default=2)
    args = ap.parse_args(argv)
    run_dir = args.run.resolve()
    summary = json.loads((run_dir / "run.json").read_text())["summary"]
    saved_dir = Path(summary["saved_fits"])
    saved_dir = saved_dir if saved_dir.is_absolute() else ROOT / saved_dir
    run = Run("sbm_coassign")
    stations, partitions, info = collect(run_dir, saved_dir, args.level)
    counts = coassignment(stations, partitions)
    rows = [{"station_a": a, "station_b": b, "fits_together": n} for (a, b), n in sorted(counts.items())]
    out = write_rows_csv(run.dir / f"coassignment_level{args.level}.csv", rows, FIELDS)
    by_count = Counter(counts.values())
    pairs_total = len(stations) * (len(stations) - 1) // 2
    distribution = {str(k): by_count.get(k, 0) for k in range(1, len(partitions) + 1)}
    print(f"level {args.level}, {len(partitions)} fits of {info['fit']}, {len(stations)} stations, "
          f"{pairs_total} pairs; never together: {pairs_total - len(counts)}")
    for k, n in distribution.items():
        print(f"together in {k:>2} of {len(partitions)} fits: {n} pairs")
    run.finish({**info, "level": args.level, "sbm_run": rel(run_dir), "saved_fits": rel(saved_dir),
                "stations": len(stations), "pairs": pairs_total, "pairs_never_together": pairs_total - len(counts),
                "pairs_by_fits_together": distribution, "output_sha256": sha256_file(out)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
