# Which TfL trip files we use

Written 2026-11-16, before any file is downloaded for the project.

## What the brief asks

Brief §1: « Dans ce projet, on s'intéressera uniquement aux trajets réalisés pendant l'année 2025. »

Brief §2.1: « Télécharger et agréger l'ensemble des fichiers contenant les trajets réalisés en 2025. »

## Rule

1. **Files for 2025.** Every file in TfL's `usage-stats/` folder named `<number>JourneyDataExtract<first day>-<last day>.csv` whose date range touches any day from 1 January 2025 to 31 December 2025.
2. **Two boundary files.** The file numbered just before the first 2025 file and the one just after the last. They are used only to check that no trip starting in 2025 sits outside the 2025 files. Their trips are not added to the 2025 data.
3. **Checks before downloading.** Every day of 2025 must be covered by at least one file, and the 2025 file numbers must have no gaps. If either check fails, the download stops.
4. **Files stored exactly as downloaded**, with a manifest of URL, size, SHA-256 and download time.

Which trips count as "2025 trips" (start date, end date, trips crossing midnight on 31 December) is a cleaning rule. It goes in `notes/cleaning-rules.md`, not here.

## What the rule selects today

From TfL's file listing read on 2026-11-16:

| Role | Files | Dates | Size |
|---|---|---|---|
| 2025 | `411…` to `434…` (24 files) | 01 Jan 2025 – 31 Dec 2025 | 1,511 MB |
| Boundary check | `410JourneyDataExtract15Dec2024-31Dec2024.csv` | 15–31 Dec 2024 | 39.6 MB |
| Boundary check | `435JourneyDataExtract01Jan2026-15Jan2026.csv` | 01–15 Jan 2026 | 39.0 MB |

Two days appear in two files each: 14 May 2025 (`419…` and `420…`) and 15 June 2025 (`421…` and `422…`). Trips on those days may be duplicated. Whether they are is not verified yet; it will be checked on the trip id (`Number`) during cleaning.

## Where the files come from

The brief links to https://cycling.data.tfl.gov.uk/#!usage-stats%2F. That page lists the files of an Amazon S3 storage bucket named `cycling.data.tfl.gov.uk`. We download from the bucket's direct address, `https://s3-eu-west-1.amazonaws.com/cycling.data.tfl.gov.uk/usage-stats/`, because the cloud session cannot reach the portal's own address. That both addresses serve identical files is not verified.
