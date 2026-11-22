# Cleaning rules

**Status: approved 2026-11-22.** R1–R3 and R6–R8 as proposed; R4 option (c); R5 flag only. Written 2026-11-22, before any cleaning code exists and before any look at the distributions of durations, trips per station or trips per day. The rules are fixed for the cleaning run; a change after this goes in a new commit that says why.

**Amendment, 2026-11-22: R9 proposed, not yet approved.** Decision D19 (b): merge the 15 `_OLD` ids into their 6-digit ids. R9 is written after the first clean run and the BikePoint match, so unlike R1–R8 it is written after looking; it says what was seen.

What has been seen of the data so far, all from the load stage (`output/runs/load/20261121T231139Z/`, your Mac): 26 files and 9,540,931 rows, of which 9,068,241 are in the 2025 files 411–434. There are no duplicate trip ids, either within a file or across files, and no value fails to parse. 184 rows have an empty end time, end station and duration. By start time, files 411–434 run from 2025-01-01 00:00 to 2025-12-31 23:59; file 410 is all 2024 and file 435 all 2026. Seen in the first lines of file 421: end station id `200025444` named "London Fields, Hackney Central_OLD".

## What the brief asks

Brief §1: « Dans ce projet, on s'intéressera uniquement aux trajets réalisés pendant l'année 2025. »

Brief §2.1: « Construire un tableau de données contenant au minimum les variables suivantes : identifiant ou nom de la station de départ ; identifiant ou nom de la station d'arrivée ; date et heure du départ ; date et heure d'arrivée ; durée du trajet. »

Brief §2.2: « Explorer les données et traiter par nettoyage les cas suivants : trajets avec station de départ ou d'arrivée manquante ; trajets de durée nulle ou négative ; trajets dont la station de départ est égale à la station d'arrivée ; incohérences éventuelles dans les noms ou identifiants de stations. »

Brief §4.1: « le poids w_ij est le nombre de trajets observés de i vers j en 2025. »

## Rules

The rules are applied in this order. A row removed by one rule is counted under that rule only.

Each rule says what it does, then the choice proposed (**Proposed**) and the other options (**Other options**). The items marked **You decide** are the ones I am not proposing a value for.

### R1. Which trips are 2025 trips

A trip is a 2025 trip if its **start time** is from 2025-01-01 00:00 to 2025-12-31 23:59, as published (London clock time). A trip that starts on 31 December 2025 and ends in 2026 counts. A trip that starts on 31 December 2024 and ends in 2025 does not.

**Proposed:** start time, because a trip is a departure from a station on a day. Every per-day, per-hour and per-weekday count in §2.3 and §3.1 then uses the same date.

**Other options:** both start and end in 2025; this differs only for trips crossing midnight at the two year ends.

Rows from the boundary files 410 and 435 are read only to check this rule. By the load run, none of their trips start in 2025.

### R2. Missing station

A trip with an empty start station id or an empty end station id is removed. It cannot be an edge of the origin–destination graph, and it has no destination for the arrival features.

From the load run, this is expected to remove the 184 rows with no end, and nothing else.

**Other options:** keep them as departures for the station's departure counts only. Then departure totals and graph out-weights would disagree by up to 184 trips.

### R3. Duration zero, negative or missing

A trip whose `duration_ms` is empty, zero or negative is removed.

### R4. Very long trips

**Decided: (c).** No upper limit in cleaning; no trip is removed for being long. How long trips affect the duration features is decided in the station-profiles note, before any profile is computed.

The options as they were put:

Whether there is an upper limit and, if so, at what value. This is the threshold I am least able to justify. The brief does not ask for one, and I have no source for a value.

- (a) No upper limit. Every trip counts in the totals and the graph. Long trips pull up the mean durations in §3.1.
- (b) Remove trips longer than a fixed limit, chosen now, before looking at durations: for example 24 hours, taken as a hire that was not a normal ride.
- (c) No limit for counts and the graph; deal with long trips only in the duration features, for example by using the median duration as well as the mean. That would be a features rule, in the station-profiles note.

### R5. Round trips (start station = end station)

**Decided: flag only.** No round trip is removed.

**Proposed:** not removed; flagged with a column `is_round_trip`. Each later stage says what it does with them. In the graph they are self-loops i → i; whether the SBM keeps self-loops is decided in the graph note.

**Other options:**
- (a) Remove all round trips.
- (b) Remove only very short round trips, as likely false starts or re-docking: for example under 60 seconds. I have no source for 60 seconds, so this would be our own threshold.

The choice was between flag-only, (a) and (b).

### R6. Duration against start and end times

Start and end times are published to the minute and `duration_ms` to the millisecond. For a consistent row, the gap `duration − (end time − start time)` is under 60 seconds in absolute value. On the two clock-change days, 30 March 2025 (01:00 → 02:00) and 26 October 2025 (02:00 → 01:00), a trip across the change has a gap near one hour.

**Proposed:** nothing removed. `duration_ms` is the duration used everywhere. Rows with a gap of 60 seconds or more are counted, split into clock-change trips and others. The "others" go into a review file, and a new rule is proposed only if they turn out to be many.

### R7. Duplicate trips under different trip ids

Two rows identical in every column except the trip id are treated as one trip. **Proposed:** keep the row with the lower trip id; count the removed ones.

Rows that share start station, start time and end station but have different bikes are separate trips, for example people riding together. They are kept.

### R8. Station ids and names

The station key is the station id, kept as text with its leading zeros.

**Proposed:**
- No station is merged with another, except under R9. Ids are kept as they are, including 9-digit ids and names ending `_OLD`. Two ids are not shown to be the same place without station locations, which are outside data (BikePoint, brief §2.1 optional).
- Every id with more than one name, and every name with more than one id, is listed in `station_names.csv` with trip counts.
- Each id is labelled by its most frequent name, with ties broken alphabetically.
- If that list shows a case that clearly needs a rule, the rule is proposed then, before any profile is computed.

### R9. `_OLD` station ids (amendment, D19 (b))

**What was seen** (clean run `output/runs/clean/20261122T124952Z/`, BikePoint match `output/runs/bikepoint/20261122T125025Z/`):
- 15 ids are a 6-digit id followed by `444` or `4444`. Every name they carry is the 6-digit id's label followed by `_OLD`.
- BikePoint lists none of the 15. It lists 14 of the 6-digit ids; 001127 is missing.
- On every day of 2025, at most one of the two ids in each pair has trips, except on at most 2 days per pair.

**Proposed:**
- An id is merged into the 6-digit id made of its first 6 characters when all of these hold: it is longer than 6 characters; every character after the first 6 is `4`; the 6-digit id exists in the trips; every name the long id carries is the 6-digit id's label followed by `_OLD`.
- The cleaning run stops with an error if the ids that meet these conditions are not exactly these 15: 001059444, 001085444, 0011274444, 001190444, 001219444, 200025444, 200083444, 200134444, 200136444, 200141444, 2001454444, 200191444, 200230444, 300032444, 300241444.
- Station names are not changed. The published ids are kept in two new columns, `start_station_id_published` and `end_station_id_published`.
- R9 runs after R7, so R7 compares the published ids. `is_round_trip` is computed after R9, on the merged ids. A trip from an `_OLD` id to its own 6-digit id therefore becomes a round trip. How many there are is not verified.
- No trip is removed by R9. Its waterfall row shows 0 removed.
- R8 then runs on the merged ids, so `station_names.csv` lists each 6-digit id with both of its names.

**Other options:**
- (a) Keep the 15 ids as separate stations (R8 as first approved).

## What the cleaning stage writes

- `data/interim/trips_clean.parquet`: the trips kept, with the load columns plus `is_round_trip` and, under R9, `start_station_id_published` and `end_station_id_published`.
- `data/interim/trips_excluded.parquet`: the trips removed, with the rule that removed each.
- In `output/runs/clean/<UTC>/`:
  - `waterfall.csv`: for each rule, the rows removed and the rows left.
  - `station_names.csv`.
  - `station_merges.csv` (R9): each merged id, the id it was merged into, and its trip starts and ends.
  - `duration_gaps.csv`: the R6 review file.
  - `run.json`.
