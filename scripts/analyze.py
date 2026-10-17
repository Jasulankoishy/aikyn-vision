"""
Command-line fallback (used when app.python-service-url is empty):
    python analyze.py <video.mov>
Prints ONE JSON object to stdout; everything else goes to stderr.
"""
import json
import os
import sys

_real_stdout = sys.stdout
sys.stdout = sys.stderr   # libraries print to stdout; the Java side parses stdout as JSON

from engine import Engine  # noqa: E402


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: analyze.py <video.mov>")
    budget = float(os.environ.get("ANALYZE_BUDGET_SEC", "240"))
    result = Engine().analyze(sys.argv[1], budget)
    # ensure_ascii=True (default): Windows would otherwise write stdout in a legacy codepage
    _real_stdout.write(json.dumps(result))
    _real_stdout.flush()


if __name__ == "__main__":
    main()
