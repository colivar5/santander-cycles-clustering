import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import bikepoint  # noqa: E402


def place(n, terminal, name="X", **extra):
    props = [{"key": "TerminalName", "value": terminal}, *({"key": k, "value": v} for k, v in extra.items())]
    return {"id": f"BikePoints_{n}", "commonName": name, "lat": 51.5 + n / 1000, "lon": -0.1,
            "additionalProperties": props}


def test_parse_flattens_properties():
    raw = json.dumps([place(2, "001002", "B", NbDocks="20"), place(1, "001001", "A")]).encode()
    df = bikepoint.parse(raw)
    assert df["bikepoint_id"].tolist() == ["BikePoints_1", "BikePoints_2"]
    assert df.loc[1, "NbDocks"] == "20" and pd.isna(df.loc[0, "NbDocks"])
    assert df["TerminalName"].tolist() == ["001001", "001002"]


def test_parse_refuses_missing_or_repeated_terminal():
    with pytest.raises(ValueError):
        bikepoint.parse(json.dumps([place(1, "001001"), place(2, "001001")]).encode())
    bad = place(1, "001001")
    bad["additionalProperties"] = []
    with pytest.raises(ValueError):
        bikepoint.parse(json.dumps([bad]).encode())
    with pytest.raises(ValueError):
        bikepoint.parse(b"{}")


def test_saved_snapshot_must_be_recorded_with_its_sha(tmp_path):
    snap = tmp_path / "BikePoint_x.json"
    snap.write_bytes(b"[]")
    sources = tmp_path / "SOURCES.csv"
    with pytest.raises(SystemExit):
        bikepoint.check_recorded(snap, sources)
    sources.write_text("file,url,retrieved_at_utc,size_bytes,sha256,used_for\n"
                       f"{snap},u,t,2,{bikepoint.sha256_file(snap)},x\n")
    bikepoint.check_recorded(snap, sources)
    snap.write_bytes(b"[ ]")
    with pytest.raises(SystemExit):
        bikepoint.check_recorded(snap, sources)


def test_match_is_exact_text():
    bp = bikepoint.parse(json.dumps([place(1, "001001", "A")]).encode())
    st = pd.DataFrame({"station_id": ["001001", "1001", "200025444"], "trip_ends": [5, 1, 2]})
    m = bikepoint.match(st, bp).set_index("station_id")
    assert m["in_bikepoint"].to_dict() == {"001001": True, "1001": False, "200025444": False}
    assert m.loc["001001", "name"] == "A"
