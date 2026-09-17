"""Compile a .netic file to grid-space HTML / JSON.

Usage (from repo root)::

    python -m netic path/to/circuit.netic
    python -m netic path/to/circuit.netic -o outdir
    python -m netic --selftest
    python -m netic path/to/circuit.netic --screenshot
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .compile import compile_netic


def write_outputs(src: str, out_dir: Path, *, title: str, screenshot: bool) -> dict:
    from .render import write_debug_html

    out_dir.mkdir(parents=True, exist_ok=True)
    result = compile_netic(src, title=title)
    (out_dir / "source.netic").write_text(src, encoding="utf-8")
    (out_dir / "grid.json").write_text(
        json.dumps(result.grid, indent=2), encoding="utf-8"
    )
    (out_dir / "issues.json").write_text(
        json.dumps([i.to_json() for i in result.issues], indent=2),
        encoding="utf-8",
    )
    html = out_dir / "grid_debug.html"
    write_debug_html(
        result.grid, str(html), issues=[i.to_json() for i in result.issues]
    )
    png_info = None
    if screenshot:
        from .screenshot import html_to_png

        png = out_dir / "screenshot.png"
        err = html_to_png(html, png)
        png_info = {"png": str(png), "error": err}
    return {
        "ok": result.ok,
        "out": str(out_dir),
        "html": str(html),
        "issues": [i.to_json() for i in result.issues],
        "screenshot": png_info,
        "components": [c["ref"] for c in result.grid.get("components") or []],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m netic")
    p.add_argument("source", nargs="?", help=".netic source file")
    p.add_argument("-o", "--out", help="output directory")
    p.add_argument("--title", help="sheet title")
    p.add_argument(
        "--screenshot",
        action="store_true",
        help="also write screenshot.png (Playwright; optional)",
    )
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)

    if args.selftest:
        import unittest
        from pathlib import Path as P

        tests_dir = P(__file__).resolve().parents[1] / "tests"
        suite = unittest.defaultTestLoader.discover(str(tests_dir), pattern="test_*.py")
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1

    if not args.source:
        p.print_help()
        return 2

    src_path = Path(args.source)
    src = src_path.read_text(encoding="utf-8")
    title = args.title or src_path.stem
    out_dir = Path(args.out) if args.out else src_path.with_suffix("")
    info = write_outputs(
        src, out_dir, title=title, screenshot=args.screenshot
    )
    print(json.dumps(info, indent=2))
    return 0 if info["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
