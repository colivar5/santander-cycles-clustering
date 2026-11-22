import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import retire  # noqa: E402


def test_moves_files_and_records_them(tmp_path):
    interim = tmp_path / "interim"
    interim.mkdir()
    a = interim / "a.parquet"
    a.write_bytes(b"abc")
    paths = retire.check([a], interim)
    rows = retire.retire(paths, interim / "retired" / "T1")
    assert not a.exists()
    assert (interim / "retired" / "T1" / "a.parquet").read_bytes() == b"abc"
    assert rows[0]["size_bytes"] == 3 and len(rows[0]["sha256"]) == 64


def test_refuses_outside_missing_and_repeated(tmp_path):
    interim = tmp_path / "interim"
    interim.mkdir()
    (tmp_path / "raw.csv").write_bytes(b"x")
    (interim / "a.parquet").write_bytes(b"x")
    with pytest.raises(SystemExit):
        retire.check([tmp_path / "raw.csv"], interim)
    with pytest.raises(SystemExit):
        retire.check([interim / "missing.parquet"], interim)
    with pytest.raises(SystemExit):
        retire.check([interim / "a.parquet", interim / "a.parquet"], interim)


def test_never_reuses_a_retired_folder(tmp_path):
    interim = tmp_path / "interim"
    (interim / "retired" / "T1").mkdir(parents=True)
    (interim / "a.parquet").write_bytes(b"x")
    with pytest.raises(FileExistsError):
        retire.retire(retire.check([interim / "a.parquet"], interim), interim / "retired" / "T1")
    assert (interim / "a.parquet").exists()
