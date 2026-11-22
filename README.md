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

## Stages

Each stage is a script that runs on its own, or all in order with `run_all.py`.

| Stage | Command | What it does | Writes |
|---|---|---|---|
| download | `env_311/bin/python src/download.py` | Downloads the TfL trip files chosen by `notes/data-selection.md` (about 1.6 GB), checks each against its size and S3's CRC64-NVME checksum, records a manifest. Files already present and matching are skipped. | `data/raw/tfl-usage-stats/*.csv` (not in git), `data/raw/MANIFEST.csv`, `data/raw/usage-stats-listing.xml`, `output/runs/download/<UTC>/run.json`, a row in `logs/runs.csv` |
| load | `env_311/bin/python src/load.py` | Checks each downloaded file against its manifest SHA-256, reads every field as text, maps columns by header name (their order differs between files), checks the row count against the file's line count, and types the columns: trip id and duration (ms) as integers, start and end times as published (London clock time, no time zone), station numbers as text with leading zeros. Keeps every row; values that do not parse become null and are listed. | `data/interim/trips_loaded.parquet` (not in git); in `output/runs/load/<UTC>/`: `per_file.csv`, `header_layouts.csv`, `daily_counts.csv`, `cross_file_ids.csv`, `parse_failures.csv`, `run.json`; a row in `logs/runs.csv` |
| clean | `env_311/bin/python src/clean.py` | Applies `notes/cleaning-rules.md`: keeps trips starting in 2025, removes trips with a missing station or a duration that is empty, zero or negative, keeps one of any rows identical except the trip id; flags round trips; lists trips whose duration disagrees with their clock times and every station id with more than one name. Long trips are kept. | `data/interim/trips_clean.parquet`, `data/interim/trips_excluded.parquet` (not in git); in `output/runs/clean/<UTC>/`: `waterfall.csv`, `station_names.csv`, `duration_gaps.csv`, `run.json`; a row in `logs/runs.csv` |

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
