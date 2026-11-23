"""Fit the stochastic block models of notes/graph-and-sbm.md (G3–G8) to the edge list.

Runs on the Python that has graph-tool (Homebrew's ``python3.15`` on the Mac,
decision D23), not env_311. Uses only graph-tool, numpy and the standard
library.

    python3.15 src/sbm.py                       # main fits (G3, G4, G8)
    python3.15 src/sbm.py --time-only           # one fit per model, prints seconds only
    python3.15 src/sbm.py --fixed-k K --deg-corr yes|no   # G7 extra fit for §4.3

Main fits: the graph without self-loops; a nested SBM, standard and
degree-corrected, each fitted ``--fits`` times (seeds 42, 43, ...), each fit
followed by ``--sweeps`` rounds of ``multiflip_mcmc_sweep(beta=inf, niter=10)``.
For each model the fit with the lowest description length is kept; the model
whose kept fit has the lower description length is the main result (G4).
That model is then fitted the same way to the graph with self-loops (G3) and
compared with the main result at the lowest level (NMI, ARI, contingency).

``--fixed-k`` fits a flat SBM with exactly K blocks to the graph without
self-loops, with the model given by ``--deg-corr`` (the one G4 kept), refined
with ``mcmc_sweep(beta=inf, niter=10, d=0, allow_vacate=False)``.

``--time-only`` runs one main fit per model at seed 42 and writes only the
seconds each took, so that ``--fits`` and ``--sweeps`` can be lowered before
any partition is seen (G8).

Each finished fit is saved at once in ``data/interim/sbm_fits/<key>/``, one
JSON file per fit, and a later run with the same key reads it instead of
fitting again. So an interrupted run is restarted by running the same command:
only the fit that was in progress is redone. The key is the SHA-256 of the
edge list, of this file and ``partitions.py``, and the graph-tool, numpy and
Python versions, the machine type and the sweep settings; anything else gives a
new key and new fits. ``key.json`` in that folder records what went into it.

Reads ``data/interim/edges.csv``. Writes in ``output/runs/sbm/<UTC>/``:
``blocks.csv`` (fit, station_id, level, block), ``fits.csv`` (one row per
fit), ``contingency_self_loops.csv`` (main fits only), ``run.json``; a row in
``logs/runs.csv``.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import INTERIM, SEED, Run, rel, sha256_file, write_json, write_rows_csv  # noqa: E402
from partitions import ari, contingency, nmi, relabel  # noqa: E402

EDGES = INTERIM / "edges.csv"
SAVED = INTERIM / "sbm_fits"
HERE = Path(__file__).resolve().parent
FITS = 10
SWEEPS = 100
NITER = 10
MODELS = {"standard": False, "degree_corrected": True}
BLOCK_FIELDS = ["fit", "station_id", "level", "block"]
FIT_FIELDS = ["fit", "model", "self_loops", "seed", "description_length", "blocks_per_level", "nmi_to_kept"]


def read_edges(path: Path) -> tuple[list[str], list[tuple[str, str, int]]]:
    """Station ids (sorted) and (source, target, weight) rows, self-loops included."""
    with open(path, newline="") as f:
        rows = [(r["source"], r["target"], int(r["weight"])) for r in csv.DictReader(f)]
    stations = sorted({s for s, _, _ in rows} | {t for _, t, _ in rows})
    return stations, rows


def edges_for(rows: list[tuple[str, str, int]], self_loops: bool) -> list[tuple[str, str, int]]:
    return [r for r in rows if self_loops or r[0] != r[1]]


def build_graph(stations: list[str], rows: list[tuple[str, str, int]]):
    import graph_tool.all as gt
    index = {s: i for i, s in enumerate(stations)}
    g = gt.Graph(directed=True)
    g.add_vertex(len(stations))
    w = g.new_ep("int64_t")
    g.add_edge_list(np.array([(index[s], index[t], n) for s, t, n in rows], dtype=np.int64), eprops=[w])
    return g, w


def seed_all(seed: int) -> None:
    import graph_tool.all as gt
    gt.seed_rng(seed)
    np.random.seed(seed)


def fit_nested(g, w, deg_corr: bool, seed: int, sweeps: int):
    import graph_tool.all as gt
    seed_all(seed)
    state = gt.minimize_nested_blockmodel_dl(g, base_state_args=dict(deg_corr=deg_corr, eweight=w))
    for _ in range(sweeps):
        state.multiflip_mcmc_sweep(beta=np.inf, niter=NITER)
    return state


def fit_fixed(g, w, deg_corr: bool, k: int, seed: int, sweeps: int):
    import graph_tool.all as gt
    seed_all(seed)
    state = gt.minimize_blockmodel_dl(g, state_args=dict(deg_corr=deg_corr, eweight=w),
                                      multilevel_mcmc_args=dict(B_min=k, B_max=k))
    for _ in range(sweeps):
        state.mcmc_sweep(beta=np.inf, niter=NITER, d=0, allow_vacate=False)
    return state


def nested_levels(state) -> list[np.ndarray]:
    """Block of each station at each level, from the lowest up to the last level with more than one block.

    A level that groups the stations exactly as the level below it is left out.
    """
    out = []
    for j in range(len(state.get_levels())):
        b = relabel(np.asarray(state.project_partition(j, 0).a))
        if out and b.max() == 0:
            break
        if out and np.array_equal(b, out[-1]):
            continue
        out.append(b)
    return out


def flat_levels(state) -> list[np.ndarray]:
    return [relabel(np.asarray(state.get_blocks().a))]


def store_key(parts: dict) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:16]


def key_parts(edges_sha256: str, sweeps: int, gt_version: str) -> dict:
    return {"edges_sha256": edges_sha256, "sbm_py_sha256": sha256_file(HERE / "sbm.py"),
            "partitions_py_sha256": sha256_file(HERE / "partitions.py"), "graph_tool": gt_version,
            "numpy": np.__version__, "python": platform.python_version(), "machine": platform.machine(),
            "sweeps": sweeps, "niter": NITER}


def load_fit(path: Path) -> dict:
    d = json.loads(path.read_text())
    return {"seed": d["seed"], "dl": d["description_length"],
            "levels": [np.asarray(b, dtype=np.int64) for b in d["levels"]], "seconds": d["seconds"],
            "saved": True}


def save_fit(path: Path, fit: dict) -> None:
    write_json(path, {"seed": fit["seed"], "description_length": fit["dl"], "seconds": fit["seconds"],
                      "levels": [[int(x) for x in b] for b in fit["levels"]]}, quiet=True)


def fit_set(name, g, w, model, deg_corr, self_loops, seeds, fit_one, levels_of, store: Path):
    """Fit once per seed, or read the fit saved in ``store``; return the kept fit, one row per fit, seconds."""
    fits = []
    for seed in seeds:
        path = store / f"{name}_seed{seed}.json"
        if path.exists():
            fits.append(load_fit(path))
            print(f"{name} seed {seed}: read from {rel(path)}", flush=True)
            continue
        t0 = time.perf_counter()
        state = fit_one(g, w, deg_corr, seed)
        fit = {"seed": seed, "dl": float(state.entropy()), "levels": levels_of(state),
               "seconds": round(time.perf_counter() - t0, 1)}
        save_fit(path, fit)
        fits.append(fit)
        print(f"{name} seed {seed}: {fit['seconds']} s, saved", flush=True)
    kept = min(fits, key=lambda f: (f["dl"], f["seed"]))
    rows = [{"fit": name, "model": model, "self_loops": self_loops, "seed": f["seed"],
             "description_length": repr(f["dl"]),
             "blocks_per_level": ";".join(str(int(b.max()) + 1) for b in f["levels"]),
             "nmi_to_kept": repr(nmi(f["levels"][0], kept["levels"][0]))} for f in fits]
    return kept, rows, {"seconds": {f["seed"]: f["seconds"] for f in fits},
                        "read_from_saved": [f["seed"] for f in fits if f.get("saved")]}


def block_rows(name: str, stations: list[str], levels: list[np.ndarray]) -> list[dict]:
    return [{"fit": name, "station_id": s, "level": lvl, "block": int(b[i])}
            for lvl, b in enumerate(levels) for i, s in enumerate(stations)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fits", type=int, default=FITS)
    ap.add_argument("--sweeps", type=int, default=SWEEPS)
    ap.add_argument("--time-only", action="store_true")
    ap.add_argument("--fixed-k", type=int)
    ap.add_argument("--deg-corr", choices=["yes", "no"])
    args = ap.parse_args(argv)
    if (args.fixed_k is None) != (args.deg_corr is None):
        ap.error("--fixed-k and --deg-corr go together")
    if args.fixed_k is not None and args.time_only:
        ap.error("--time-only is for the main fits")

    import graph_tool.all as gt
    gt.openmp_set_num_threads(1)
    run = Run("sbm")
    stations, rows = read_edges(EDGES)
    plain = build_graph(stations, edges_for(rows, self_loops=False))
    seeds = list(range(SEED, SEED + args.fits))
    settings = {"edges": rel(EDGES), "edges_sha256": sha256_file(EDGES), "stations": len(stations),
                "graph_tool": gt.__version__, "numpy": np.__version__, "threads": 1,
                "fits": args.fits, "sweeps": args.sweeps, "niter": NITER, "seeds": seeds}
    if not args.time_only:
        parts = key_parts(settings["edges_sha256"], args.sweeps, gt.__version__)
        store = SAVED / store_key(parts)
        write_json(store / "key.json", parts, quiet=True)
        settings["saved_fits"] = rel(store)

    def nested_fit(sweeps):
        return lambda g, w, dc, seed: fit_nested(g, w, dc, seed, sweeps)

    if args.time_only:
        seconds = {}
        for model, dc in MODELS.items():
            t0 = time.perf_counter()
            fit_nested(*plain, dc, SEED, args.sweeps)
            seconds[model] = round(time.perf_counter() - t0, 1)
            print(f"{model}: one fit took {seconds[model]} s", flush=True)
        run.finish({**settings, "mode": "time_only", "seconds_per_fit": seconds})
        return 0

    if args.fixed_k is not None:
        dc = args.deg_corr == "yes"
        model = "degree_corrected" if dc else "standard"
        name = f"fixed_k_{args.fixed_k}_{model}"
        kept, fit_rows, secs = fit_set(name, *plain, model, dc, False, seeds,
                                       lambda g, w, d, s: fit_fixed(g, w, d, args.fixed_k, s, args.sweeps),
                                       flat_levels, store)
        if int(kept["levels"][0].max()) + 1 != args.fixed_k:
            raise SystemExit(f"kept fit has {int(kept['levels'][0].max()) + 1} blocks, not {args.fixed_k}")
        write_rows_csv(run.dir / "blocks.csv", block_rows(name, stations, kept["levels"]), BLOCK_FIELDS)
        write_rows_csv(run.dir / "fits.csv", fit_rows, FIT_FIELDS)
        run.finish({**settings, "mode": "fixed_k", "k": args.fixed_k, "model": model,
                    "kept_seed": kept["seed"], "kept_description_length": kept["dl"], "seconds": secs})
        return 0

    kept, all_fit_rows, all_blocks, secs = {}, [], [], {}
    for model, dc in MODELS.items():
        kept[model], fr, secs[model] = fit_set(model, *plain, model, dc, False, seeds,
                                               nested_fit(args.sweeps), nested_levels, store)
        all_fit_rows += fr
        all_blocks += block_rows(model, stations, kept[model]["levels"])
    main_model = min(MODELS, key=lambda m: kept[m]["dl"])

    loops = build_graph(stations, edges_for(rows, self_loops=True))
    name = f"self_loops_{main_model}"
    kept_loops, fr, secs[name] = fit_set(name, *loops, main_model, MODELS[main_model], True, seeds,
                                         nested_fit(args.sweeps), nested_levels, store)
    all_fit_rows += fr
    all_blocks += block_rows(name, stations, kept_loops["levels"])

    a, b = kept[main_model]["levels"][0], kept_loops["levels"][0]
    table = contingency(a, b)
    cont_rows = [{"main_block": i, "self_loops_block": j, "stations": int(table[i, j])}
                 for i in range(table.shape[0]) for j in range(table.shape[1]) if table[i, j]]

    write_rows_csv(run.dir / "blocks.csv", all_blocks, BLOCK_FIELDS)
    write_rows_csv(run.dir / "fits.csv", all_fit_rows, FIT_FIELDS)
    write_rows_csv(run.dir / "contingency_self_loops.csv", cont_rows,
                   ["main_block", "self_loops_block", "stations"])
    print(f"main model (lower description length): {main_model}")
    run.finish({**settings, "mode": "main", "main_model": main_model,
                "kept": {m: {"seed": k["seed"], "description_length": k["dl"],
                             "blocks_per_level": [int(x.max()) + 1 for x in k["levels"]]}
                         for m, k in {**kept, name: kept_loops}.items()},
                "self_loops_comparison_level_0": {"nmi": nmi(a, b), "ari": ari(a, b)},
                "seconds": secs})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
