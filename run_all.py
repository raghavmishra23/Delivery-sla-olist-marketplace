"""Rebuilds every artefact in the project from the source dataset, in order."""

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable

STEPS = [
    ("database/fetch_data.py", "download and unpack the source dataset"),
    ("database/clean_data.py", "apply the data-quality rules"),
    ("database/load_data.py", "rebuild the SQLite database"),
    ("database/run_queries.py", "run the SQL suite and export the mart"),
    ("dashboard/build_dashboard_data.py", "pack the dashboard payload"),
    ("excel/build_workbook.py", "build the Excel workbook"),
    ("database/reconcile.py", "reconcile the KPIs across every tool"),
]


def run(script, note):
    print(f"\n=== {script} — {note} ===", flush=True)
    started = time.time()
    result = subprocess.run([PY, str(ROOT / script)], cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit(f"\n{script} failed with exit code {result.returncode}")
    print(f"--- {script} done in {time.time() - started:.1f}s", flush=True)


def main():
    started = time.time()
    for script, note in STEPS:
        run(script, note)
    print(f"\nall steps completed in {time.time() - started:.1f}s")


if __name__ == "__main__":
    main()
