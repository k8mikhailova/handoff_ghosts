"""CLI: python -m ghosts <directory-of-notes | note files...>"""
from __future__ import annotations

import sys
from pathlib import Path

from .parsing import load_directory, load_meetings
from .pipeline import analyze
from .report import render_markdown


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m ghosts <notes-directory | file1.md file2.md ...>", file=sys.stderr)
        return 2
    paths = [Path(a) for a in argv]
    meetings = load_directory(paths[0]) if len(paths) == 1 and paths[0].is_dir() else load_meetings(paths)
    print(render_markdown(analyze(meetings)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
