#!/usr/bin/env python3
"""Run on the home PC; compile host checks only in an owned temporary folder."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "frontend/cache-analysis"), str(ROOT / "tools")]
from cache_record import decode_metadata


def run(command, cwd=ROOT):
    subprocess.run(command, cwd=cwd, check=True)


def main():
    # Spotify's frontend is not redistributed. Tests derive their inputs from a
    # local copy of the pinned bundle, which build_patch.py verifies by hash.
    original = ROOT / "frontend/spotifytv.js"
    if not original.exists():
        sys.exit("Missing frontend/spotifytv.js. Fetch it with:\n  curl --compressed -o frontend/spotifytv.js "
                 "https://tv.scdn.co/ps5/v2/f1b1b7e/js/spotifytv.js")
    run([sys.executable, "frontend/standalone/build_patch.py"])
    record = ROOT / "frontend/cache-analysis/spotifytv-record.original"
    record.write_bytes((ROOT / "frontend/cache-analysis/spotifytv-record.header").read_bytes() + original.read_bytes())
    decode_metadata(record.read_bytes())
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "tools"), str(ROOT / "frontend/cache-analysis")])
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=ROOT, env=env, check=True)
    sanitizer_env=env.copy()
    sanitizer_env.update(SPOTLESS_TEST_CC="clang",SPOTLESS_TEST_SANITIZE="1")
    subprocess.run([sys.executable,"-m","unittest","discover","-s","tests","-p","test_watcher.py","-v"],cwd=ROOT,env=sanitizer_env,check=True)
    run([sys.executable, "test_cache_record.py"], ROOT / "frontend/cache-analysis")
    run([sys.executable, "test_builder.py"], ROOT / "frontend/standalone")
    run([sys.executable, "browser_tests.py", "--timeout", "45"], ROOT / "frontend/standalone")


if __name__ == "__main__":
    main()
