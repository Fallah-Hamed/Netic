#!/usr/bin/env python3
"""
schematic_tools.render_svg — human-only debug HTML for grid-space JSON.

Usage:
    python -m schematic_tools.render_svg grid.json --out debug.html

Writes a styled HTML file with a sized-IC SVG. Never intended for LLM context.
"""

from __future__ import annotations

import argparse, html, json, sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


_PAL = {
    "+3V3": "#e31a1c", "VDD": "#e31a1c", "VCC": "#e31a1c",
    "GND": "#238b45", "VSS": "#238b45",
    "NRST": "#2171b5",
    "OSC_IN": "#7b3294", "OSC_OUT": "#7b3294",
    "USER_LED": "#d94801", "LED_GND": "#02818a",
}

def _xml_escape(text: str) -> str:
    return html.escape(str(text), quote=True)


_KIND_FILL = {
    "ic": "#fff9c4",
    "ic_gnd": "#e8f5e9",  # pale green — bulk GND multi-unit
    "cap": "#c6dbef",
    "resistor": "#fcbba1",
    "inductor": "#c7d2fe",
    "crystal": "#d4b9da",
    "led": "#a1d99b",
    "switch": "#fdd0a2",
    "transistor": "#ffe0b2",  # MOSFET / BJT discrete
    "connector": "#e0e7ff",  # indigo-tint header / SIM / RF
    "aux_ic": "#fef3c7",  # amber — secondary IC in cluster
    "other": "#eeeeee",
}


def _ic_pin_world(comp: dict) -> List[dict]:
    """Main-IC pins with world coords / stubs when ``place_symbol`` ran."""
    gx = float(comp.get("gx") or 0.0)
    gy = float(comp.get("gy") or 0.0)
    out: List[dict] = []
    pins = comp.get("pins") or {}
    if not isinstance(pins, dict):
        return out
    for pid, spec in pins.items():
        if not isinstance(spec, dict):
            continue
        if "x" not in spec or "y" not in spec:
            continue
        wx = gx + float(spec["x"])
        wy = gy + float(spec["y"])
        stub = spec.get("stub") or []
        world_stub = []
        for pt in stub:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                world_stub.append([gx + float(pt[0]), gy + float(pt[1])])
        face = str(spec.get("face") or "")
        if not face:
            faces = comp.get("pin_faces") or {}
            face = str(faces.get(pid) or faces.get(str(spec.get("name") or pid)) or "")
        out.append({
            "id": str(pid),
            "name": str(spec.get("name") or pid),
            "face": face,
            "group": str(spec.get("group") or ""),
            "color": str(spec.get("color") or "#454545"),
            "x": wx,
            "y": wy,
            "stub": world_stub,
        })
    return out


def _grid_ports(grid: dict) -> List[Tuple[str, list]]:
    """Bundle attach dots: [(net, [x, y])] from final grid or abstract branch.

    Final grid: ``meta.abstract.debug.branch_ports[].ports`` (main-grid coords).
    Abstract branch grid: ``meta.ports`` (local coords).
    """
    out: List[Tuple[str, list]] = []
    meta = grid.get("meta") or {}
    abs_debug = ((meta.get("abstract") or {}).get("debug")) or {}
    for bp in abs_debug.get("branch_ports") or []:
        for nm, xy in (bp.get("ports") or {}).items():
            if isinstance(xy, (list, tuple)) and len(xy) >= 2:
                out.append((str(nm), [float(xy[0]), float(xy[1])]))
    for nm, xy in (meta.get("ports") or {}).items():
        if isinstance(xy, (list, tuple)) and len(xy) >= 2:
            out.append((str(nm), [float(xy[0]), float(xy[1])]))
    return out


def _grid_rats(grid: dict) -> List[dict]:
    """L3 preview airwires: box port → matching main-IC pin(s)."""
    meta = grid.get("meta") or {}
    items = meta.get("ratsnests") or grid.get("ratsnests") or []
    return [r for r in items if isinstance(r, dict)]


def _junction_points(wires: List[dict], comps: List[dict], eps: float = 1e-6) -> List[tuple]:
    """Points where 3+ wire arms meet (T-junctions / crossings).

    A segment contributes 1 arm at each of its endpoints and 2 arms when the
    point lies strictly inside it (collinear T). Plain wire ends and bends
    (2 arms) get no dot; points on a component face are excluded.
    """
    segs: List[tuple] = []
    seen_segs = set()
    for w in wires:
        path = w.get("path") or []
        for a, b in zip(path, path[1:]):
            s = ((float(a[0]), float(a[1])), (float(b[0]), float(b[1])))
            key = (min(s), max(s))
            if key in seen_segs:
                continue  # same segment drawn twice (e.g. re-walked rails)
            seen_segs.add(key)
            segs.append(s)

    def between(p: tuple, a: tuple, b: tuple) -> bool:
        if abs(a[0] - b[0]) < eps:  # vertical segment
            return abs(p[0] - a[0]) < eps and min(a[1], b[1]) + eps < p[1] < max(a[1], b[1]) - eps
        if abs(a[1] - b[1]) < eps:  # horizontal segment
            return abs(p[1] - a[1]) < eps and min(a[0], b[0]) + eps < p[0] < max(a[0], b[0]) - eps
        return False

    def on_end(p: tuple, a: tuple, b: tuple) -> bool:
        return (abs(p[0] - a[0]) < eps and abs(p[1] - a[1]) < eps) or \
               (abs(p[0] - b[0]) < eps and abs(p[1] - b[1]) < eps)

    def on_any_body_face(p: tuple) -> bool:
        for c in comps:
            gx, gy = float(c["gx"]), float(c["gy"])
            ww, hh = float(c.get("w", 1)), float(c.get("h", 1))
            pins = c.get("pins") or {}
            if isinstance(pins, dict):
                for spec in pins.values():
                    if isinstance(spec, dict) and "x" in spec and "y" in spec:
                        fx = gx + float(spec["x"])
                        fy = gy + float(spec["y"])
                        if abs(p[0] - fx) < 0.2 and abs(p[1] - fy) < 0.2:
                            return True
            faces = (
                (gx - ww / 2, gy),
                (gx + ww / 2, gy),
                (gx, gy + hh / 2),
                (gx, gy - hh / 2),
            )
            for fx, fy in faces:
                if abs(p[0] - fx) < 0.2 and abs(p[1] - fy) < 0.2:
                    return True
        return False

    out: List[tuple] = []
    seen = set()
    for a, b in segs:
        for p in (a, b):
            key = (round(p[0]), round(p[1]))
            if key in seen:
                continue
            seen.add(key)
            arms = 0
            for s, t in segs:
                if on_end(p, s, t):
                    arms += 1
                elif between(p, s, t):
                    arms += 2
            if arms >= 3 and not on_any_body_face(p):
                out.append(p)
    return out


def render_svg(
    grid: dict,
    cell: int = 36,
    *,
    show_debug_boxes: bool = False,
    issues: Optional[List[dict]] = None,
) -> str:
    """Return an SVG string for a sized grid-space JSON.

    Recursion / network bounding boxes stay in the grid JSON for L3
    (outermost frame). They are not drawn unless ``show_debug_boxes``.
    """
    comps = grid.get("components", [])
    wires = grid.get("wires", [])
    ps = grid.get("power_symbols", [])

    xs: List[float] = []
    ys: List[float] = []
    for c in comps:
        hw, hh = c.get("w", 1) / 2, c.get("h", 1) / 2
        xs += [c["gx"] - hw, c["gx"] + hw]
        ys += [c["gy"] - hh, c["gy"] + hh]
        for pin in _ic_pin_world(c):
            xs.append(pin["x"]); ys.append(pin["y"])
    for p in ps:
        xs.append(p["gx"]); ys.append(p["gy"])
    for w in wires:
        for pt in w.get("path", []):
            xs.append(pt[0]); ys.append(pt[1])
    # Include hierarchy boxes in view bounds only when they are drawn.
    if show_debug_boxes:
        for box in (grid.get("meta", {}) or {}).get("debug_boxes") or []:
            try:
                xs.extend([float(box["x0"]), float(box["x1"])])
                ys.extend([float(box["y0"]), float(box["y1"])])
            except (KeyError, TypeError, ValueError):
                pass
    # Bundle attach ports (net → [x, y]) in view bounds
    for _nm, xy in _grid_ports(grid):
        try:
            xs.append(float(xy[0])); ys.append(float(xy[1]))
        except (KeyError, TypeError, ValueError):
            pass
    for rat in _grid_rats(grid):
        for pt in rat.get("path") or []:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                xs.append(float(pt[0])); ys.append(float(pt[1]))

    if not xs:
        return ('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
                '</svg>')

    pad = 4
    min_x, max_x = int(min(xs)) - pad, int(max(xs)) + pad
    min_y, max_y = int(min(ys)) - pad, int(max(ys)) + pad
    # Extra margin so pin labels stay inside the viewBox.
    margin = 48

    def sx(gx: float) -> float:
        return (gx - min_x) * cell + margin

    def sy(gy: float) -> float:
        # y-up internal → y-down SVG
        return (max_y - gy) * cell + margin

    def net_color(nm: str) -> str:
        if nm in _PAL:
            return _PAL[nm]
        u = nm.upper()
        if u.startswith("GND") or u.startswith("VSS"):
            return _PAL["GND"]
        if u.startswith("+") or u.startswith("VDD") or u.startswith("VCC"):
            return _PAL["+3V3"]
        return "#454545"

    ww = (max_x - min_x) * cell + margin * 2
    hh = (max_y - min_y) * cell + margin * 2

    out: List[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {ww} {hh}" '
        f'width="{ww}" height="{hh}">',
        '<rect width="100%" height="100%" fill="#f8f9fa"/>',
    ]

    # Faint integer grid
    for gx in range(min_x, max_x + 1):
        for gy in range(min_y, max_y + 1):
            out.append(
                f'<circle cx="{sx(gx):.1f}" cy="{sy(gy):.1f}" r="1.1" fill="#dee2e6"/>'
            )

    # Axis crosshair at origin
    out.append(
        f'<line x1="{sx(min_x):.1f}" y1="{sy(0):.1f}" x2="{sx(max_x):.1f}" '
        f'y2="{sy(0):.1f}" stroke="#cbd5e1" stroke-width="1" stroke-dasharray="4 3"/>'
    )
    out.append(
        f'<line x1="{sx(0):.1f}" y1="{sy(min_y):.1f}" x2="{sx(0):.1f}" '
        f'y2="{sy(max_y):.1f}" stroke="#cbd5e1" stroke-width="1" stroke-dasharray="4 3"/>'
    )

    # Wires under components
    for w in wires:
        col = net_color(w.get("net", ""))
        path = w.get("path", [])
        if len(path) < 2:
            continue
        pts = " ".join(f"{sx(p[0]):.1f},{sy(p[1]):.1f}" for p in path)
        out.append(
            f'<polyline points="{pts}" fill="none" stroke="{col}" '
            f'stroke-width="2.6" stroke-linejoin="round" '
            f'stroke-linecap="round" opacity="0.9"/>'
        )
        # Mid-path net label for long signal wires
        mid = path[len(path) // 2]
        if w.get("net") not in ("GND",) and len(path) >= 2:
            out.append(
                f'<text x="{sx(mid[0]) + 4:.1f}" y="{sy(mid[1]) - 6:.1f}" '
                f'font-size="9" font-family="monospace" fill="{col}" '
                f'opacity="0.85">{w["net"]}</text>'
            )

    # Junction dots: only where 3+ wire arms meet (T-junctions / crossings) —
    # never at plain wire ends, bends, or on a component face.
    for pt in _junction_points(wires, comps):
        out.append(
            f'<circle cx="{sx(pt[0]):.1f}" cy="{sy(pt[1]):.1f}" r="3.2" fill="#111"/>'
        )

    # Components (sized rectangles)
    for c in comps:
        w_c, h_c = c.get("w", 1), c.get("h", 1)
        cx, cy = sx(c["gx"]), sy(c["gy"])
        # Body spans w × h grid cells
        bw = w_c * cell - 4
        bh = h_c * cell - 4
        x0 = cx - bw / 2
        y0 = cy - bh / 2
        fill = _KIND_FILL.get(c.get("kind", "other"), "#eeeeee")
        is_ic = c.get("kind") == "ic"
        is_ic_gnd = c.get("kind") == "ic_gnd"
        is_conn = c.get("kind") == "connector"
        is_aux = c.get("kind") == "aux_ic"
        is_body = is_ic or is_ic_gnd or is_conn or is_aux
        stroke = (
            "#1565c0" if is_ic else
            "#2e7d32" if is_ic_gnd else
            "#4338ca" if is_conn else
            "#b45309" if is_aux else
            "#444"
        )
        sw = 3.2 if is_body else 1.8
        rx = 8 if is_body else 4
        out.append(
            f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}" rx="{rx}"/>'
        )
        # Main-IC pins: one edge dot + label inside the body, next to the pin.
        ic_pins = _ic_pin_world(c) if is_ic else []
        if is_ic and ic_pins:
            for pin in ic_pins:
                col = pin["color"] or "#454545"
                px, py = sx(pin["x"]), sy(pin["y"])
                out.append(
                    f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.2" '
                    f'fill="{col}" stroke="#1a1a1a" stroke-width="0.8"/>'
                )
                face = pin["face"]
                if face == "left":
                    lx, ly, anchor, baseline = px + 6.0, py, "start", "middle"
                elif face == "right":
                    lx, ly, anchor, baseline = px - 6.0, py, "end", "middle"
                elif face == "top":
                    lx, ly, anchor, baseline = px, py + 9.0, "middle", "hanging"
                else:
                    lx, ly, anchor, baseline = px, py - 5.0, "middle", "auto"
                out.append(
                    f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" '
                    f'dominant-baseline="{baseline}" font-size="9" '
                    f'font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" '
                    f'fill="{col}">{_xml_escape(pin["name"])}</text>'
                )
        elif is_ic:
            out.append(
                f'<text x="{cx:.1f}" y="{y0 + 14:.1f}" text-anchor="middle" '
                f'font-size="10" font-family="monospace" fill="#1565c0">VDD ↑</text>'
            )
            # Empty bottom when bulk-GND multi-unit exists for this IC
            has_subunit = any(
                cc.get("kind") == "ic_gnd" and cc.get("parent_ref") == c["ref"]
                for cc in comps
            )
            if has_subunit:
                out.append(
                    f'<text x="{cx:.1f}" y="{y0 + bh - 6:.1f}" text-anchor="middle" '
                    f'font-size="10" font-family="monospace" fill="#999">'
                    f'(GND → {c["ref"]}_GND)</text>'
                )
            else:
                out.append(
                    f'<text x="{cx:.1f}" y="{y0 + bh - 6:.1f}" text-anchor="middle" '
                    f'font-size="10" font-family="monospace" fill="#238b45">GND ↓</text>'
                )
            out.append(
                f'<text x="{x0 + 8:.1f}" y="{cy + 4:.1f}" text-anchor="start" '
                f'font-size="10" font-family="monospace" fill="#666">signals</text>'
            )
            out.append(
                f'<text x="{x0 + bw - 8:.1f}" y="{cy + 4:.1f}" text-anchor="end" '
                f'font-size="10" font-family="monospace" fill="#666">signals</text>'
            )
        elif is_ic_gnd:
            # Bulk GND multi-unit: sides only (no VDD top / no bottom GND row)
            out.append(
                f'<text x="{x0 + 6:.1f}" y="{cy + 4:.1f}" text-anchor="start" '
                f'font-size="10" font-family="monospace" fill="#2e7d32">GND</text>'
            )
            out.append(
                f'<text x="{x0 + bw - 6:.1f}" y="{cy + 4:.1f}" text-anchor="end" '
                f'font-size="10" font-family="monospace" fill="#2e7d32">GND</text>'
            )
            parent = c.get("parent_ref") or ""
            if parent:
                out.append(
                    f'<text x="{cx:.1f}" y="{y0 + 14:.1f}" text-anchor="middle" '
                    f'font-size="9" font-family="monospace" fill="#558b2f">'
                    f'unit of {parent}</text>'
                )

        label = c["ref"]
        if c.get("value") and not is_body:
            label = f'{c["ref"]}'
        fs = 13 if is_body else 11
        fw = "bold" if is_body else "600"
        out.append(
            f'<text x="{cx:.1f}" y="{cy + 4:.1f}" text-anchor="middle" '
            f'font-size="{fs}" font-family="system-ui,sans-serif" fill="#1a1a1a" '
            f'font-weight="{fw}">{label}</text>'
        )
        if is_ic and c.get("value"):
            out.append(
                f'<text x="{cx:.1f}" y="{cy + 18:.1f}" text-anchor="middle" '
                f'font-size="10" font-family="monospace" fill="#555">{_xml_escape(c["value"])}</text>'
            )
        elif not is_ic:
            orient = c.get("orientation", "")[:1].upper()
            tier = c.get("proximity_tier", "")[:1].upper()
            out.append(
                f'<text x="{cx:.1f}" y="{cy + 16:.1f}" text-anchor="middle" '
                f'font-size="8" font-family="monospace" fill="#666">'
                f'{c.get("value","")} {orient}/{tier}</text>'
            )

    # Power symbols (orientation/facing: open away from attach wire)
    for p in ps:
        px, py = sx(p["gx"]), sy(p["gy"])
        s = cell * 0.32
        nm = p.get("net", "")
        facing = (p.get("facing") or "down").lower()
        orient = (p.get("orientation") or "vertical").lower()
        is_gnd = "GND" in nm.upper() or nm.upper().startswith("VSS")
        if is_gnd:
            # Default vertical: stem from above, bars below (facing down)
            # Horizontal: stem from attach side, bars open facing left/right
            if orient == "horizontal" or facing in ("left", "right"):
                # stem along ±x into bars further in facing direction
                if facing == "left":
                    # wire from right; bars to the left
                    out.append(
                        f'<line x1="{px + s:.1f}" y1="{py:.1f}" x2="{px:.1f}" '
                        f'y2="{py:.1f}" stroke="#238b45" stroke-width="2"/>'
                    )
                    for k, w in ((0.0, 2.4), (0.45, 2.0), (0.9, 1.8)):
                        out.append(
                            f'<line x1="{px - s * k:.1f}" y1="{py - s * (1 - k * 0.5):.1f}" '
                            f'x2="{px - s * k:.1f}" y2="{py + s * (1 - k * 0.5):.1f}" '
                            f'stroke="#238b45" stroke-width="{w}"/>'
                        )
                else:
                    out.append(
                        f'<line x1="{px - s:.1f}" y1="{py:.1f}" x2="{px:.1f}" '
                        f'y2="{py:.1f}" stroke="#238b45" stroke-width="2"/>'
                    )
                    for k, w in ((0.0, 2.4), (0.45, 2.0), (0.9, 1.8)):
                        out.append(
                            f'<line x1="{px + s * k:.1f}" y1="{py - s * (1 - k * 0.5):.1f}" '
                            f'x2="{px + s * k:.1f}" y2="{py + s * (1 - k * 0.5):.1f}" '
                            f'stroke="#238b45" stroke-width="{w}"/>'
                        )
            else:
                # vertical facing down (or up)
                if facing == "up":
                    out.append(
                        f'<line x1="{px:.1f}" y1="{py + s:.1f}" x2="{px:.1f}" '
                        f'y2="{py:.1f}" stroke="#238b45" stroke-width="2"/>'
                    )
                    for k, w in ((0.0, 2.4), (0.45, 2.0), (0.9, 1.8)):
                        out.append(
                            f'<line x1="{px - s * (1 - k * 0.5):.1f}" '
                            f'y1="{py - s * k:.1f}" '
                            f'x2="{px + s * (1 - k * 0.5):.1f}" '
                            f'y2="{py - s * k:.1f}" '
                            f'stroke="#238b45" stroke-width="{w}"/>'
                        )
                else:
                    out.append(
                        f'<line x1="{px - s:.1f}" y1="{py:.1f}" x2="{px + s:.1f}" '
                        f'y2="{py:.1f}" stroke="#238b45" stroke-width="2.4"/>'
                    )
                    out.append(
                        f'<line x1="{px - s * 0.66:.1f}" y1="{py + s * 0.45:.1f}" '
                        f'x2="{px + s * 0.66:.1f}" y2="{py + s * 0.45:.1f}" '
                        f'stroke="#238b45" stroke-width="2"/>'
                    )
                    out.append(
                        f'<line x1="{px - s * 0.33:.1f}" y1="{py + s * 0.9:.1f}" '
                        f'x2="{px + s * 0.33:.1f}" y2="{py + s * 0.9:.1f}" '
                        f'stroke="#238b45" stroke-width="1.8"/>'
                    )
                    out.append(
                        f'<line x1="{px:.1f}" y1="{py - s:.1f}" x2="{px:.1f}" '
                        f'y2="{py:.1f}" stroke="#238b45" stroke-width="2"/>'
                    )
        else:
            # V+ / rail: arrow opens along facing
            if orient == "horizontal" or facing in ("left", "right"):
                if facing == "right":
                    out.append(
                        f'<line x1="{px - s * 0.6:.1f}" y1="{py:.1f}" '
                        f'x2="{px + s * 0.2:.1f}" y2="{py:.1f}" '
                        f'stroke="#e31a1c" stroke-width="2.4"/>'
                    )
                    out.append(
                        f'<polygon points="{px + s * 0.85:.1f},{py:.1f} '
                        f'{px + s * 0.15:.1f},{py - s * 0.45:.1f} '
                        f'{px + s * 0.15:.1f},{py + s * 0.45:.1f}" fill="#e31a1c"/>'
                    )
                    out.append(
                        f'<line x1="{px - s * 0.6:.1f}" y1="{py - s * 0.35:.1f}" '
                        f'x2="{px - s * 0.6:.1f}" y2="{py + s * 0.35:.1f}" '
                        f'stroke="#e31a1c" stroke-width="2"/>'
                    )
                else:
                    out.append(
                        f'<line x1="{px + s * 0.6:.1f}" y1="{py:.1f}" '
                        f'x2="{px - s * 0.2:.1f}" y2="{py:.1f}" '
                        f'stroke="#e31a1c" stroke-width="2.4"/>'
                    )
                    out.append(
                        f'<polygon points="{px - s * 0.85:.1f},{py:.1f} '
                        f'{px - s * 0.15:.1f},{py - s * 0.45:.1f} '
                        f'{px - s * 0.15:.1f},{py + s * 0.45:.1f}" fill="#e31a1c"/>'
                    )
                    out.append(
                        f'<line x1="{px + s * 0.6:.1f}" y1="{py - s * 0.35:.1f}" '
                        f'x2="{px + s * 0.6:.1f}" y2="{py + s * 0.35:.1f}" '
                        f'stroke="#e31a1c" stroke-width="2"/>'
                    )
            else:
                # vertical: arrow up (default)
                out.append(
                    f'<line x1="{px:.1f}" y1="{py + s * 0.6:.1f}" x2="{px:.1f}" '
                    f'y2="{py - s * 0.6:.1f}" stroke="#e31a1c" stroke-width="2.4"/>'
                )
                out.append(
                    f'<polygon points="{px - s * 0.45:.1f},{py - s * 0.3:.1f} '
                    f'{px:.1f},{py - s * 0.85:.1f} {px + s * 0.45:.1f},{py - s * 0.3:.1f}" '
                    f'fill="#e31a1c"/>'
                )
                out.append(
                    f'<line x1="{px - s * 0.35:.1f}" y1="{py + s * 0.6:.1f}" '
                    f'x2="{px + s * 0.35:.1f}" y2="{py + s * 0.6:.1f}" '
                    f'stroke="#e31a1c" stroke-width="2"/>'
                )
        label = nm
        out.append(
            f'<text x="{px + s + 6:.1f}" y="{py + 3:.1f}" '
            f'font-size="9" font-family="monospace" fill="#555">{label}</text>'
        )

    # Net labels (stubs + text at free end)
    for lab in grid.get("labels", []):
        color = net_color(lab.get("net", ""))
        for stub in lab.get("stubs", []):
            path = stub.get("path") or []
            if len(path) < 2:
                continue
            pts = " ".join(
                f"{sx(float(p[0])):.1f},{sy(float(p[1])):.1f}" for p in path
            )
            out.append(
                f'<polyline points="{pts}" fill="none" stroke="{color}" '
                f'stroke-width="1.6" stroke-dasharray="4 3" opacity="0.9"/>'
            )
            end = path[-1]
            ex, ey = sx(float(end[0])), sy(float(end[1]))
            out.append(
                f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="3" fill="{color}" '
                f'opacity="0.85"/>'
            )
            out.append(
                f'<text x="{ex + 6:.1f}" y="{ey - 4:.1f}" font-size="10" '
                f'font-family="monospace" fill="{color}" font-weight="600">'
                f'{lab.get("text") or lab.get("net", "")}</text>'
            )

    # Recursion / aux-network boxes stay in JSON for L3. Draw only on request.
    debug_boxes = (
        grid.get("meta", {}).get("debug_boxes")
        or grid.get("debug_boxes")
        or []
    ) if show_debug_boxes else []
    # Sort by level ascending so outer levels draw under inner
    for box in sorted(debug_boxes, key=lambda b: int(b.get("level", 1))):
        try:
            x0 = float(box["x0"])
            y0 = float(box["y0"])
            x1 = float(box["x1"])
            y1 = float(box["y1"])
        except (KeyError, TypeError, ValueError):
            continue
        level = int(box.get("level", 1) or 1)
        color = box.get("color") or (
            "#2563eb", "#dc2626", "#16a34a", "#ca8a04",
            "#9333ea", "#0891b2", "#ea580c", "#db2777",
        )[(level - 1) % 8]
        label = str(box.get("label") or level)
        # SVG y is flipped: top of box is max gy
        rx = sx(min(x0, x1))
        ry = sy(max(y0, y1))
        rw = abs(x1 - x0) * cell
        rh = abs(y1 - y0) * cell
        # slight outward pad in pixels by level for nested visibility
        pad_px = 2 + (level - 1) * 1.5
        rx -= pad_px
        ry -= pad_px
        rw += 2 * pad_px
        rh += 2 * pad_px
        dash = "6 3" if level == 1 else "4 2"
        out.append(
            f'<rect x="{rx:.1f}" y="{ry:.1f}" width="{rw:.1f}" height="{rh:.1f}" '
            f'fill="none" stroke="{color}" stroke-width="2.2" '
            f'stroke-dasharray="{dash}" opacity="0.95" rx="3"/>'
        )
        # Tiny level number just outside top-left of box
        out.append(
            f'<circle cx="{rx - 2:.1f}" cy="{ry - 2:.1f}" r="8" '
            f'fill="{color}" opacity="0.95"/>'
        )
        out.append(
            f'<text x="{rx - 2:.1f}" y="{ry + 2:.1f}" text-anchor="middle" '
            f'font-size="10" font-family="monospace" font-weight="700" '
            f'fill="#fff">{label}</text>'
        )
        net = box.get("net") or ""
        if net and box.get("kind") == "aux_network":
            out.append(
                f'<text x="{rx + 10:.1f}" y="{ry - 4:.1f}" '
                f'font-size="9" font-family="monospace" fill="{color}" '
                f'opacity="0.9">{net}</text>'
            )

    # Bundle attach dots — the points top-level wiring connects to the main
    # IC (cross marker, per net colour)
    for nm, xy in _grid_ports(grid):
        x, y = sx(float(xy[0])), sy(float(xy[1]))
        col = net_color(nm)
        r = 5.5
        out.append(
            f'<line x1="{x - r:.1f}" y1="{y:.1f}" x2="{x + r:.1f}" y2="{y:.1f}" '
            f'stroke="#ffffff" stroke-width="5.5" stroke-linecap="round"/>'
        )
        out.append(
            f'<line x1="{x:.1f}" y1="{y - r:.1f}" x2="{x:.1f}" y2="{y + r:.1f}" '
            f'stroke="#ffffff" stroke-width="5.5" stroke-linecap="round"/>'
        )
        out.append(
            f'<line x1="{x - r:.1f}" y1="{y:.1f}" x2="{x + r:.1f}" y2="{y:.1f}" '
            f'stroke="{col}" stroke-width="2.4" stroke-linecap="round"/>'
        )
        out.append(
            f'<line x1="{x:.1f}" y1="{y - r:.1f}" x2="{x:.1f}" y2="{y + r:.1f}" '
            f'stroke="{col}" stroke-width="2.4" stroke-linecap="round"/>'
        )
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1.6" fill="{col}"/>')
        out.append(
            f'<text x="{x + 8:.1f}" y="{y - 5:.1f}" font-size="9" '
            f'font-family="monospace" fill="{col}" font-weight="700" '
            f'opacity="0.95">{nm}</text>'
        )

    # L3 ratsnests: dashed airwire from each bundle port to matching IC pin(s).
    # Drawn last so the required attach is visible over interiors.
    for rat in _grid_rats(grid):
        path = rat.get("path") or []
        if len(path) < 2:
            continue
        try:
            pts = " ".join(
                f"{sx(float(p[0])):.1f},{sy(float(p[1])):.1f}" for p in path
            )
        except (TypeError, ValueError, IndexError):
            continue
        col = net_color(str(rat.get("net") or ""))
        out.append(
            f'<polyline points="{pts}" fill="none" stroke="{col}" '
            f'stroke-width="1.8" stroke-dasharray="7 4" stroke-linecap="round" '
            f'opacity="0.8"/>'
        )

    # Issue markers (errors/warnings from Netic)
    issue_list = issues if issues is not None else (grid.get("issues") or [])
    for iss in issue_list:
        if not isinstance(iss, dict):
            continue
        at = iss.get("at")
        if not (isinstance(at, (list, tuple)) and len(at) >= 2):
            continue
        try:
            ix, iy = float(at[0]), float(at[1])
        except (TypeError, ValueError):
            continue
        sev = str(iss.get("severity") or "WARNING").upper()
        col = "#dc2626" if sev == "ERROR" else "#d97706"
        px, py = sx(ix), sy(iy)
        out.append(
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="7" fill="none" '
            f'stroke="{col}" stroke-width="2" opacity="0.9"/>'
        )
        code = _xml_escape(str(iss.get("code") or sev))
        out.append(
            f'<text x="{px + 10:.1f}" y="{py - 8:.1f}" font-size="9" '
            f'font-family="monospace" fill="{col}" font-weight="700">{code}</text>'
        )

    # Coordinate legend
    out.append(
        f'<text x="{margin}" y="{hh - 18}" font-size="11" '
        f'font-family="monospace" fill="#64748b">'
        f'grid y-up · origin (0,0) · cell={cell}px · + = bundle attach dot</text>'
    )
    out.append("</svg>")
    return "\n".join(out)


def write_debug_html(
    grid: dict,
    path: str,
    *,
    show_debug_boxes: bool = False,
    issues: Optional[List[dict]] = None,
) -> dict:
    svg = render_svg(grid, show_debug_boxes=show_debug_boxes, issues=issues)
    meta = grid.get("meta", {})
    board = meta.get("board", "Board")
    sheet = meta.get("sheet", board)
    main_ic = meta.get("main_ic", "")

    net_counts: Dict[str, int] = {}
    for w in grid.get("wires", []):
        nm = w["net"]
        net_counts[nm] = net_counts.get(nm, 0) + 1

    net_rows = "".join(
        f'<tr><td style="color:{_PAL.get(nm, "#454545")}">●</td>'
        f'<td>{nm}</td><td>{cnt}</td></tr>'
        for nm, cnt in sorted(net_counts.items())
    )

    comp_rows = "".join(
        f'<tr><td>{c["ref"]}</td><td>{c.get("kind","")}</td>'
        f'<td>({c["gx"]},{c["gy"]})</td>'
        f'<td>{c.get("w",1)}×{c.get("h",1)}</td>'
        f'<td>{c.get("orientation","")[:1]}/{c.get("proximity_tier","")[:1]}</td></tr>'
        for c in grid.get("components", [])
    )

    issue_list = issues if issues is not None else (grid.get("issues") or [])
    issue_rows = "".join(
        f'<tr><td style="color:{"#f87171" if str(i.get("severity")).upper()=="ERROR" else "#fbbf24"}">'
        f'{html.escape(str(i.get("severity") or ""))}</td>'
        f'<td>{html.escape(str(i.get("code") or ""))}</td>'
        f'<td>{html.escape(str(i.get("message") or ""))}</td></tr>'
        for i in issue_list if isinstance(i, dict)
    )
    if not issue_rows:
        issue_rows = '<tr><td colspan="3" style="color:#64748b">none</td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{board} — Schematic Grid (Step 1)</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0;
         margin: 0; padding: 24px; }}
  h1 {{ text-align: center; color: #f8fafc; margin-bottom: 4px; font-size: 22px; }}
  .sub {{ text-align: center; color: #94a3b8; font-size: 13px; margin-bottom: 20px; }}
  .wrap {{ display: flex; gap: 18px; max-width: 1600px; margin: 0 auto; align-items: flex-start; }}
  .card {{ background: #fff; border-radius: 12px; padding: 14px; overflow: auto; flex: 1; }}
  .card svg {{ display: block; margin: 0 auto; }}
  .side {{ width: 240px; flex-shrink: 0; }}
  .side h3 {{ margin: 0 0 8px; font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: .04em; }}
  .side table {{ width: 100%; font-size: 12px; border-collapse: collapse; margin-bottom: 18px; }}
  .side td, .side th {{ padding: 3px 6px; text-align: left; }}
  .side th {{ color: #64748b; font-weight: 600; }}
  .panel {{ background: #1e293b; border-radius: 10px; padding: 12px; margin-bottom: 12px; }}
  .legend {{ max-width: 900px; margin: 18px auto 0; font-size: 12px; color: #94a3b8; text-align: center; line-height: 1.8; }}
  .legend span {{ display: inline-block; width: 12px; height: 12px; border-radius: 2px;
                  margin: 0 4px; vertical-align: middle; border: 1px solid #334155; }}
</style></head><body>
<h1>{board} — Step 1: Sized Schematic Grid</h1>
<div class="sub">
  sheet={sheet} · main_ic={main_ic or "—"} · template v{meta.get("template_version", "?")}<br>
  IC body is a sized rectangle (VDD top / GND bottom / signals on sides).
  Auxiliaries are 1×1. Wires are Manhattan paths in grid units (y-up).
</div>
<div class="wrap">
  <div class="side">
    <div class="panel">
      <h3>Components</h3>
      <table>
        <tr><th>Ref</th><th>Kind</th><th>Pos</th><th>Size</th><th>O/T</th></tr>
        {comp_rows}
      </table>
    </div>
    <div class="panel">
      <h3>Nets</h3>
      <table>
        <tr><th></th><th>Net</th><th>Wires</th></tr>
        {net_rows}
      </table>
    </div>
    <div class="panel">
      <h3>Issues</h3>
      <table>
        <tr><th>Sev</th><th>Code</th><th>Msg</th></tr>
        {issue_rows}
      </table>
    </div>
  </div>
  <div class="card">{svg}</div>
</div>
<div class="legend">
  <span style="background:#fff9c4;border-color:#1565c0"></span> IC
  <span style="background:#c6dbef"></span> Cap
  <span style="background:#fcbba1"></span> Resistor
  <span style="background:#d4b9da"></span> Crystal
  <span style="background:#a1d99b"></span> LED
  <span style="background:#fdd0a2"></span> Switch
  &nbsp;|&nbsp;
  <span style="background:#e31a1c"></span> +3V3
  <span style="background:#238b45"></span> GND
  <span style="background:#2171b5"></span> NRST
  <span style="background:#7b3294"></span> OSC
  <span style="background:#d94801"></span> USER_LED
  &nbsp;|&nbsp; O/T = Orientation/Tier (V|H / I|O)
</div>
</body></html>
"""
    Path(path).write_text(html, encoding="utf-8")
    return {"ok": True, "html": path, "components": len(grid.get("components", [])),
            "wires": len(grid.get("wires", [])),
            "power_symbols": len(grid.get("power_symbols", []))}


def write_svg(grid: dict, path: str, *, show_debug_boxes: bool = False) -> dict:
    """Write a standalone SVG with real selectable <text> pin names."""
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_svg(grid, show_debug_boxes=show_debug_boxes), encoding="utf-8")
    return {"ok": True, "svg": str(dest)}


def main():
    ap = argparse.ArgumentParser(description="render_svg — human debug HTML")
    ap.add_argument("grid", help="Grid JSON file")
    ap.add_argument("--out", required=True, help="Output HTML path")
    ap.add_argument(
        "--show-debug-boxes",
        action="store_true",
        help="Draw nested recursion bounding boxes (hidden by default)",
    )
    args = ap.parse_args()

    try:
        grid = json.loads(Path(args.grid).read_text(encoding="utf-8"))
        result = write_debug_html(
            grid, args.out, show_debug_boxes=args.show_debug_boxes,
        )
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
