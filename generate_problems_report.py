"""Local helper that writes PROBLEMS_REPORT.md.

This file is kept in the repo so the trailing-newline and whitespace
warnings have a known-good copy. Run it on your machine if you want a
fresh report.
"""

from __future__ import annotations

from pathlib import Path


def main() -> None:
    out = Path("PROBLEMS_REPORT.md")
    out.write_text("# PoliSim Problems Report\n\nRun your scanners and paste results here.\n", encoding="utf-8")


if __name__ == "__main__":
    main()
file_path="/workspace/artifacts/Modern-TK80-Inference/generate_problems_report.py"