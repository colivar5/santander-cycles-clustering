import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import download  # noqa: E402

NAMES = [
    "409JourneyDataExtract01Dec2024-14Dec2024.csv",
    "410JourneyDataExtract15Dec2024-31Dec2024.csv",
    "411JourneyDataExtract01Jan2025-14Jan2025.csv",
    "412JourneyDataExtract15Jan2025-31Jan2025.csv",
    "413JourneyDataExtract01Feb2025-14Feb2025.csv",
    "414JourneyDataExtract15Feb2025-28Feb2025.csv",
    "415JourneyDataExtract01Mar2025-14Mar2025.csv",
    "416JourneyDataExtract15Mar2025-31Mar2025.csv",
    "417JourneyDataExtract01Apr2025-14Apr2025.csv",
    "418JourneyDataExtract15Apr2025-30Apr2025.csv",
    "419JourneyDataExtract01May2025-14May2025.csv",
    "420JourneyDataExtract14May2025-31May2025.csv",
    "421JourneyDataExtract01Jun2025-15Jun2025.csv",
    "422JourneyDataExtract15Jun2025-30Jun2025.csv",
    "423JourneyDataExtract01Jul2025-15Jul2025.csv",
    "424JourneyDataExtract16Jul2025-31Jul2025.csv",
    "425JourneyDataExtract01Aug2025-15Aug2025.csv",
    "426JourneyDataExtract16Aug2025-31Aug2025.csv",
    "427JourneyDataExtract01Sep2025-15Sep2025.csv",
    "428JourneyDataExtract16Sep2025-30Sep2025.csv",
    "429JourneyDataExtract01Oct2025-15Oct2025.csv",
    "430JourneyDataExtract16Oct2025-31Oct2025.csv",
    "431JourneyDataExtract01Nov2025-15Nov2025.csv",
    "432JourneyDataExtract16Nov2025-30Nov2025.csv",
    "433JourneyDataExtract01Dec2025-15Dec2025.csv",
    "434JourneyDataExtract16Dec2025-31Dec2025.csv",
    "435JourneyDataExtract01Jan2026-15Jan2026.csv",
    "436JourneyDataExtract16Jan2026-31Jan2026.csv",
]


def listing(names):
    items = "".join(
        f"<Contents><Key>usage-stats/{n}</Key><LastModified>2026-01-14T00:00:00.000Z</LastModified>"
        f"<ETag>&quot;{'0' * 32}&quot;</ETag><Size>100</Size><StorageClass>STANDARD</StorageClass></Contents>"
        for n in ["", "cycling-load.json", "9b-Journey-Data-Extract-06Sep15-19Sep15.csv", *names])
    return (f'<?xml version="1.0" encoding="UTF-8"?><ListBucketResult '
            f'xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Name>x</Name><IsTruncated>false</IsTruncated>'
            f"{items}</ListBucketResult>").encode()


def test_parse_day():
    assert download.parse_day("14May2025") == dt.date(2025, 5, 14)
    assert download.parse_day("01Sep2025") == dt.date(2025, 9, 1)


def test_selection_and_boundaries():
    files = download.parse_listing([listing(NAMES)])
    assert len(files) == len(NAMES)
    year, boundary = download.select(files)
    assert [f.number for f in year] == list(range(411, 435))
    assert [f.number for f in boundary] == [410, 435]


def test_coverage_finds_overlap_and_no_gap():
    year, _ = download.select(download.parse_listing([listing(NAMES)]))
    cov = download.coverage(year)
    assert cov["days_covered"] == 365
    assert cov["missing_days"] == []
    assert cov["overlapping_days"] == {"2025-05-14": [419, 420], "2025-06-15": [421, 422]}


def test_crc64nvme_matches_published_check_value(tmp_path):
    p = tmp_path / "check.txt"
    p.write_bytes(b"123456789")
    expected = bytes.fromhex("ae8b14860a799888")
    import base64
    assert download.crc64nvme_file(p) == base64.b64encode(expected).decode()


def test_coverage_reports_gap():
    names = [n for n in NAMES if not n.startswith("425")]
    files = download.parse_listing([listing(names)])
    year = [f for f in files if 411 <= f.number <= 424]
    cov = download.coverage(year)
    assert "2025-08-01" in cov["missing_days"]
