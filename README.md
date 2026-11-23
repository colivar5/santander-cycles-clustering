# santander-cycles-clustering

Course project for *Apprentissage non supervisé* (Madalina Olteanu, Executive Master 2025–2026, Université Paris Dauphine PSL): clustering the London Santander Cycles network from TfL's 2025 trip data, first from station profiles (PCA, a non-linear projection, clustering, anomaly detection), then from the origin–destination graph (stochastic block model), and comparing the two.

Status: set-up. This README grows with each stage.

## Set-up

Python 3.11. From the repository folder, first check that no `env_311` folder exists, because `python -m venv` on an existing folder rewrites it without asking. This should say "No such file or directory":

```bash
ls env_311
```

Then create the environment and install the pinned packages:

```bash
python3.11 -m venv env_311
```

```bash
env_311/bin/pip install -r requirements.txt
```

The sbm stage needs graph-tool, which is not on PyPI. On macOS it comes from Homebrew, for Homebrew's own Python 3.15 (tested with graph-tool 3.9 and numpy 2.5.5):

```bash
brew install graph-tool
```

Check that it imports:

```bash
/opt/homebrew/opt/python@3.15/bin/python3.15 -B -c "import graph_tool, numpy; print(graph_tool.__version__, numpy.__version__)"
```

## Stages

Each stage is a script that runs on its own, or all in order with `run_all.py`.

| Stage | Command | What it does | Writes |
|---|---|---|---|
| download | `env_311/bin/python src/download.py` | Downloads the TfL trip files chosen by `notes/data-selection.md` (about 1.6 GB), checks each against its size and S3's CRC64-NVME checksum, records a manifest. Files already present and matching are skipped. | `data/raw/tfl-usage-stats/*.csv` (not in git), `data/raw/MANIFEST.csv`, `data/raw/usage-stats-listing.xml`, `output/runs/download/<UTC>/run.json`, a row in `logs/runs.csv` |
| load | `env_311/bin/python src/load.py` | Checks each downloaded file against its manifest SHA-256, reads every field as text, maps columns by header name (their order differs between files), checks the row count against the file's line count, and types the columns: trip id and duration (ms) as integers, start and end times as published (London clock time, no time zone), station numbers as text with leading zeros. Keeps every row; values that do not parse become null and are listed. | `data/interim/trips_loaded.parquet` (not in git); in `output/runs/load/<UTC>/`: `per_file.csv`, `header_layouts.csv`, `daily_counts.csv`, `cross_file_ids.csv`, `parse_failures.csv`, `run.json`; a row in `logs/runs.csv` |
| clean | `env_311/bin/python src/clean.py` | Applies `notes/cleaning-rules.md`: keeps trips starting in 2025, removes trips with a missing station or a duration that is empty, zero or negative, keeps one of any rows identical except the trip id; merges the 15 `_OLD` station ids into their 6-digit ids, keeping the published ids (R9); removes trips starting or ending at a mechanical workshop (R10); flags round trips; lists trips whose duration disagrees with their clock times and every station id with more than one name. Long trips are kept. | `data/interim/trips_clean.parquet`, `data/interim/trips_excluded.parquet` (not in git); in `output/runs/clean/<UTC>/`: `waterfall.csv`, `station_names.csv`, `station_merges.csv`, `duration_gaps.csv`, `run.json`; a row in `logs/runs.csv` |
| bikepoint | `env_311/bin/python src/bikepoint.py` | Fetches TfL's BikePoint station list (brief §2.1, optional; needs api.tfl.gov.uk), keeps the response exactly as received, flattens it to one row per station, and matches each trip station id to BikePoint's `TerminalName`, as text. `--file PATH` re-reads a saved snapshot without fetching, and only if `data/external/SOURCES.csv` records it with the same SHA-256. `run_all.py` runs it with `--file` on the committed snapshot `data/external/bikepoint/BikePoint_20261122T125026Z.json` and never fetches. | `data/external/bikepoint/BikePoint_<UTC>.json`, a row in `data/external/SOURCES.csv`, `data/interim/bikepoint_stations.csv`; in `output/runs/bikepoint/<UTC>/`: `match.csv`, `run.json`; a row in `logs/runs.csv` |
| graph | `env_311/bin/python src/graph.py` | Builds the directed weighted origin–destination edge list (brief §4.1, `notes/graph-and-sbm.md`): w_ij is the number of trips from station i to station j on the merged ids; round trips are kept as self-loops and flagged. | `data/interim/edges.csv` (not in git); `output/runs/graph/<UTC>/run.json`; a row in `logs/runs.csv` |
| sbm | `/opt/homebrew/opt/python@3.15/bin/python3.15 src/sbm.py` | Fits the SBMs of `notes/graph-and-sbm.md` with graph-tool, on Homebrew's Python 3.15, not env_311 (decision D23): nested standard and degree-corrected SBMs without self-loops, 10 fits each (seeds 42–51), keeping the lower description length; the kept model refitted with self-loops and compared (NMI, ARI). `--time-only` times one fit per model and writes nothing else; `--fixed-k K --deg-corr yes\|no` is the extra fit for §4.3. One thread. Each finished fit is saved at once; after an interruption, run the same command again and only the fit that was in progress is redone. | `data/interim/sbm_fits/<key>/` (one JSON per fit, plus `key.json`; not in git); in `output/runs/sbm/<UTC>/`: `blocks.csv`, `fits.csv`, `contingency_self_loops.csv`, `run.json`; a row in `logs/runs.csv` |
| retire (not in `run_all.py`) | `env_311/bin/python src/retire.py FILE...` | Before re-running a stage whose rules changed: moves the named files from `data/interim/` into `data/interim/retired/<UTC>/`, recording their size and SHA-256, so the next stage reads the new output instead of the old one. Nothing is deleted or replaced. | `data/interim/retired/<UTC>/` with the moved files and `retired.csv`; `output/runs/retire/<UTC>/run.json`; a row in `logs/runs.csv` |

All stages in order:

```bash
env_311/bin/python src/run_all.py
```

From a given stage onwards: `env_311/bin/python src/run_all.py --from <stage>`. Each stage runs in its own process; the first failure stops the run. The full output is also saved to `output/run_all/<UTC>.log`.

## Rules

- Raw files are kept exactly as downloaded; every transformation is code.
- No result file is ever replaced: identical content is left alone, different content is written beside the old file with a UTC timestamp in its name, and a `NOTE` line says so (`src/common.py`).
- Choices that results could steer are written in `notes/` and committed before the run they govern.
- Seed 42 everywhere.

## Layout

- `src/` one script per stage, plus `common.py` (paths, seed, the never-overwrite writer, run records)
- `tests/` unit tests (`env_311/bin/python -m pytest -q`)
- `data/raw/` downloaded files and their manifest; `data/interim/` derived data (rebuilt by code, not in git); `data/external/` outside data
- `output/` figures and summaries; `output/runs/<stage>/<UTC>/` one folder per run
- `logs/runs.csv` one row per run
- `notes/` rules written before running
