"""Run every stage in order, each in its own process, stopping at the first failure.

    python src/run_all.py                  # all stages
    python src/run_all.py --from <stage>   # from this stage onwards

Output of each run goes to the terminal and to ``output/run_all/<UTC stamp>.log``.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUTPUT, ROOT, rel, utc_stamp  # noqa: E402

STAGES = ["download", "load", "clean"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="start", choices=STAGES, default=STAGES[0])
    args = ap.parse_args(argv)
    stages = STAGES[STAGES.index(args.start):]

    log_dir = OUTPUT / "run_all"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{utc_stamp()}.log"
    with open(log_path, "x") as log:
        for stage in stages:
            header = f"=== {stage} ===\n"
            print(header, end="")
            log.write(header)
            proc = subprocess.Popen([sys.executable, str(ROOT / "src" / f"{stage}.py")], cwd=ROOT,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    env={**os.environ, "PYTHONUNBUFFERED": "1"})
            for line in proc.stdout:
                print(line, end="")
                log.write(line)
            code = proc.wait()
            if code != 0:
                msg = f"FAILED {stage} (exit {code}); stopping. Log: {rel(log_path)}\n"
                print(msg, end="")
                log.write(msg)
                return code
        msg = f"all {len(stages)} stage(s) done. Log: {rel(log_path)}\n"
        print(msg, end="")
        log.write(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
