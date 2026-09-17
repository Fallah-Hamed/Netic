# Netic

**Netic** is a small domain-specific language for analog schematic *topology*.

Its purpose is to give LLMs a way to describe a schematic circuit in text —
relative walks on a grid, not coordinates — so they can produce a neat,
readable schematic for a human without doing geometric calculations.

The LLM writes `*.netic` text. A Python compiler walks it onto an integer
grid, checks overlaps, and emits grid JSON + HTML. Absolute coordinates do
not matter. The walk *is* the net.

It is not Circuitikz, not KiCad, not SPICE, not SKiDL/CDL, and not a placer.
SKiDL describes connectivity. SPICE simulates that connectivity. Netic is the
schematic itself, as a program.

Grammar: [`SYNTAX.md`](SYNTAX.md) (v0.3).

## Install

Python 3.10+. Stdlib only for compile + HTML. Playwright is optional (PNG).

```bash
cd Netic
# no pip package required — run from this folder
python -m netic --selftest
python -m netic examples/04_common_emitter.netic -o out/ce
```

PNG (optional):

```bash
python -m netic examples/01_rc_lpf.netic -o out/lpf --screenshot
```

## What a program is

- Cursor starts at `(0, 0)` with no heading.
- `r l u d` (or `R L U D`) draw **1** grid of wire. Four directions only. No half-grid.
- Two-pin bodies are **2×2** squares (terminals two grid points apart), collinear with the walk. Arrival sets orientation.
- Transistors are the same **2×2** square: pins sit on the four face centres (BJT `B C E`; MOSFET `G D S B` with bulk on the remaining face).
- After a two-pin, the cursor is on the far pin. After `Q`/`M`/GND/PWR/`label`, it stays.
- `move { r u }` is air travel (no ink). Prefer `to C` / `@Q1:C` for transistor pins.
- `(name)` marks a drawing point (not a net). `@name` jumps there.
- `pulldown` / `pullup` / `bank` / `tap { … }` draw a branch and return to the call site.

Compile errors go back to the LLM as JSON (`issues.json`). The picture is still written.

## Layout

```
Netic/
  SYNTAX.md          LLM-facing grammar
  README.md          this file
  netic/             compiler (parser, walk, checker, HTML render)
  examples/*.netic   language tests — not BOMs
  tests/             parser + walk benches
```

## Issue codes (compiler → LLM)

Errors: `syntax`, `body_overlap`, `wire_through_body`, `no_heading`,
`unknown_anchor`, `dup_ref`, `net_conflict`, `bad_stub`, `bank_pitch`,
`pullup_net`.

Warnings: `wire_cross`, `face_tangent`, `body_spacing`, `symbol_on_pin`.

Origin: analog pen-walk work in LLM2KiCAD (`drawlang`, 2026-08-29). Netic is
the standalone language project. The frozen L2–L4 placer is not this repo.
