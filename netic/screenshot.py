"""Render grid-debug HTML to PNG via Playwright.

Used by Netic (`python -m netic …`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

_GRID_SELECTORS = (".card svg", ".card", "svg")


def html_to_png(
    html: Path,
    png: Path,
    *,
    width: int = 1600,
    height: int = 1200,
    scale: float = 1.0,
    wait_ms: int = 500,
    full_page: bool = False,
) -> Optional[str]:
    """Render html to png. Returns an error string, or None on success.

    Default clips to the grid canvas, not the chrome around it.
    """
    html = Path(html)
    png = Path(png)
    if not html.is_file():
        return f"missing html: {html}"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "playwright not installed (pip install playwright; python -m playwright install chromium)"
    try:
        png.parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(
                viewport={"width": width, "height": height},
                device_scale_factor=scale,
            )
            page.goto(html.resolve().as_uri(), wait_until="load")
            page.wait_for_timeout(wait_ms)
            _screenshot_grid(page, png, full_page=full_page)
            browser.close()
        return None
    except Exception as e:
        return str(e)


def _screenshot_grid(page, png: Path, *, full_page: bool = False) -> None:
    if not full_page:
        for sel in _GRID_SELECTORS:
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.first.screenshot(path=str(png))
                return
    page.screenshot(path=str(png), full_page=True)
