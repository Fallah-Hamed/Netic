# Netic — relative grid-space schematic language

**Version:** 0.3

**Audience:** LLM authors and the Python interpreter

**Files:** `*.netic`

**Compile:** `python -m netic path/to/circuit.netic -o outdir`

The program **steers the tip of a pen**. There are no absolute coordinates.
The compiler starts at `(0, 0)` and walks. Every body is a **2×2 square**.
Four directions only. Every step is **one grid point**. Orthogonal wires only.

This is not Circuitikz, not KiCad S-expression, not SPICE/SKiDL/CDL, and not a
placer. `examples/*.netic` files are language tests, not BOMs. The compile
result is a grid-space drawing.

Do **not** use placer vocabulary (`seed_pin`, `side_bundles`, orientation hints).

---

## 1. How the pen works

- `r l u d` = draw wire **1** grid right / left / up / down.
- `R L U D` mean the same thing (one grid). There is no half-grid step.
- The walk **is** the wire. Relative geometry only.
- Incoming direction sets two-pin **orientation**. No extra face token.
- Wire always hits a two-pin face **orthogonally**. The part is collinear with the walk.
- After a two-pin / source, the pen is on the **far** terminal, same heading.
- After `Q` / `M`, GND, PWR, or `label`, the pen **stays**.
- Newlines and extra spaces are whitespace. `#` starts a comment to end of line.

Start of program: pen at `(0, 0)`, no heading yet. First `r/l/u/d` (or `move`) sets it.

All positions snap to the **integer grid**.

---

## 2. Two-pin parts

```
Res R1 10k
Cap C1 100n
Ind L1 10n
Dio D1
Led D2
Sw  S1
Xtal Y1 16MHz
```

Form: `KIND  [REF]  [VALUE]`

| Token | Meaning | Grid body |
|---|---|---|
| `Res` | resistor | 2×2 |
| `Cap` | capacitor | 2×2 |
| `Ind` | inductor | 2×2 |
| `Dio` | diode (arrival = **anode**, exit = cathode) | 2×2 |
| `Led` | LED (arrival = **anode**) | 2×2 |
| `Sw`  | switch | 2×2 |
| `Xtal` | crystal | 2×2 |

A two-pin occupies **two grid points**: the near pin is the pen, the far pin is
**2** steps forward. The body is a 2×2 square whose left/right (or top/bottom)
face centres are those pins.

`REF` starts with a letter (`R1`, `C3`). If omitted, the compiler assigns `R1`, `C1`, …

`VALUE` is one token (`10k`, `100n`, `2N3904`). No spaces.

Example — resistor to the right, then more wire:

```
r Res R1 10k r
```

Walk: 1 right onto the near pin → body occupies the next 2 right → pen on far pin → 1 more wire right.

---

## 3. Ground, power, sources, labels

Point symbols — **pen does not move**:

```
GND
GND:AGND
PWR:VCC
PWR:3V3
PWR:+5V
label VIN
net  VIN
```

- `GND` names that point `GND` (or `GND:NAME`).
- `PWR:NAME` is a power symbol with that net name.
- `label NAME` / `net NAME` tags the current point (ports like `VIN` / `VOUT`).

Two-pin **sources** (same 2×2 body as other two-pins):

```
Vsrc:P V1 5V
Vsrc:N V1 5V
Isrc:P I1 1mA
```

`:P` = this arrival pin is the **positive** (current leaves `P` for `Isrc`).

`:N` = arrival is the negative. Default if omitted: `:P`.

---

## 4. Transistors (2×2 square)

```
Q:B Q1 2N3904
Q:B npn Q1 2N3904
Q:C pnp Q2
M:G nmos M1
M:D pmos M2
```

Pins: BJT `B C E` — MOSFET `G D S B` (`B` = bulk / body).

The device is a **2×2 square**. Each terminal sits on the **centre of a face**.
The **named pin is the arrival face**. The square sits **forward** along the
current heading.

Typical amplifier pose — walk **horizontally** onto `Q:B` or `M:G`:

- arrival face = base / gate
- **top** = collector / drain
- **bottom** = emitter / source
- **opposite** = MOSFET bulk (`B`); unused on a BJT

From the base, collector is **not** a wire through the device. Air-move or pin-jump:

```
r Q:B npn Q1 2N3904
move { r u }
```

`move { r u }` lifts the pen: 1 right + 1 up and drops on the collector. No ink.

Form: `move { <steps> }` — steps are only `r l u d` (or `R L U D`). Alias: `MOV`.

Device type optional: `npn` `pnp` `nmos` `pmos`. Default `Q` → npn, `M` → nmos.

After `Q:B` the pen is still on the **base**.

### Pin jumps

Every placed body registers anchors `REF:PIN` at its pins. Heading is **outward**
(off the face), so the next draw walks away from the part.

```
r Q:B npn Q1 2N3904
to C
u Res Rc 1k u PWR:VCC
```

`to C` (alias `pin C`) jumps to pin C of the part the pen is currently on.
`@Q1:C` does the same by name. MOSFET bulk is `@M1:B` / `to B`.

`move { r u }` still works — it is the primitive. Prefer `to C` / `@Q1:C`.

---

## 5. Anchors (drawing points, not net names)

Mark a junction you will return to:

```
(vin)
```

Jump the pen there (lift, no ink). Heading is restored to whatever it was when the anchor was defined:

```
@vin
```

Example — series R then a cap to ground, then continue the series:

```
r (n1) Res R1 1k r (n2)
d Cap C1 100n d GND
@n2
r Res R2 1k r
```

`(name)` is a **coordinate on the drawing**. It is not a net name. Use `label` / `GND` / `PWR` for nets.

---

## 6. Macros (draw a branch, pen returns)

Like LaTeX `\frac{ }{ }` — a function. **No anchor required.** After the macro, the pen is back at the call site with the same heading.

### Pull-down / pull-up

```
pulldown{1 Cap C3}
pulldown{1 Cap C3 100n}
pulldown{1 Cap C3 100n AGND}
pullup{1 Res R2 10k VCC}
pullup{2 Res R2 10k 3V3}
```

Arguments inside `{ }`, commas optional:

`stub  KIND  REF  [VALUE]  [FAR_NET]`

- `stub` is a **positive integer** (number of 1-grid interconnects on each side of the part).
- Pull-down default far net = `GND`. Equivalent of `pulldown{1 Cap C3}` is `d Cap C3 d GND`.
- Pull-up uses `u` instead of `d`. Far net required for a named rail (`VCC`, `3V3`, `+5V`, …).
- Sibling pull-ups/pull-downs should use the **same stub** so their rail symbols land on one row.

### Parallel bank (decoupling / many pull-ups)

A **horizontal row of vertical branches**. First branch hangs from the call point.
A same-net rail is drawn between hang points. The pen returns.

```
bank{down, 1, 3, forward, Cap C1 100n, Cap C2 1u, Cap C3 10u}
bank{up, 1, 3, forward, Res R1 10k, Res R2 10k}
```

Arguments:

1. `down` or `up` — branch direction
2. stub length (positive integer)
3. **pitch** of hang points (integer, must be ≥ 3 so 2×2 bodies have ≥ 1 gap; `3` is typical)
4. `forward` or `backward` — along ±X from the call point (`forward` follows the last horizontal heading, default `+X`)
5. parts in draw order: `KIND REF [VALUE]`, comma-separated

### General branch — `tap { … }`

Like pull-up/pull-down, but any sequence. The pen is saved, the body is drawn,
then the pen returns to the call site with the same heading. This is the
**policy primitive** for “drop a branch here”:

```
r (n1) tap { d Cap C1 100n d GND } r Res R2 1k
```

`pulldown{…}` / `pullup{…}` remain sugar for the common vertical two-pin case.

---

## 7. What the compiler does

1. Walk the text from the start and place.
2. If a new body **overlaps** another body → `ERROR body_overlap`.
3. If a **drawn** wire goes through a body interior → `ERROR wire_through_body`. Landing on a face is the connection; that is allowed.
4. Different-net wires crossing mid-span → `WARNING wire_cross`. Sharing a point is a junction (OK).
5. A drawn wire running **along a component face** (tangent to an edge) → `WARNING face_tangent`. Connect at pins, perpendicular — branches leave from the **middle of a stem**, never from the component face.
6. Two bodies closer than **1 grid edge-to-edge** → `WARNING body_spacing`. Sibling branches sit at least one grid apart.
7. A power/ground symbol sitting directly **on a two-pin part's pin** → `WARNING symbol_on_pin`. Leave a stub of wire (1 or more) between the part and its symbol.
8. Unknown token / missing heading / unknown `@name` → `ERROR`.

Junction dots are drawn only where **three or more wire arms meet** (T-junctions and
crossings) — never at plain wire ends or on component faces.

**Drawing practices (recommended, not enforced by the compiler):**

- **Branches at stem centers** — a branch (vertical off a horizontal stem, or
  horizontal off a vertical stem) attaches at the **midpoint** of that stem. The
  stem is the straight wire between its two endpoints; the midpoint must land on
  the integer grid, so stems have even length.
- **Equal interconnects** — the two wires attached to a passive's two pins run the
  **same length** to the nearest junction dot / pin / symbol / label.
- **One rail row** — power/ground symbols of the same net should share one row (or
  column): sibling branches sit on the same row so their rail symbols line up.
  Not always feasible — use judgment.
- **Sibling rows** — components in neighboring parallel branches (Re with Ce, Rb
  with Re) share the same y so the branch row reads as one aligned bank.
- All positions snap to the integer grid.

Issues are returned as JSON (`issues.json`) so an LLM can revise the text. The picture is still written so a human can see it.

Connected ink + pins share a net. `GND` / `PWR` / `label` / `net` name that node. A two-pin does **not** short its two terminals.

---

## 8. Out of scope (v0.3)

- Integrated circuits / multi-pin boxes (syntax is not complete enough yet)
- Hierarchical sheets, nested clusters
- Non-orthogonal / diagonal moves
- Half-grid steps
- Absolute coordinates
- KiCad / Altium / EasyEDA export
- Old placer fields (`seed_pin`, `side_bundles`, orientation hints)

---

## 9. Tiny examples

**RC low-pass (series R, shunt C to ground, output after R):**

```
# RC LPF
label VIN
r Res R1 1k r (vout)
pulldown{2 Cap C1 100n}
label VOUT
```

**Common-emitter (orthogonal, collector up; branches from stem middles, rails aligned):**

```
# CE amplifier
label VIN
r Cap Cin 100n r (base)
pullup{2 Res Rb1 47k VCC}
pulldown{2 Res Rb2 10k}
r r (qb) Q:B npn Q1 2N3904
to C
(vc)
u u Res Rc 1k u PWR:VCC
@vc
move { u }
r r Cap Cout 100n r
label VOUT
@qb
to E
(ve)
d d Res Re 100 d GND
@ve
move { d }
r r r
pulldown{1 Cap Ce 10u}
```

**Decoupling row from a rail:**

```
PWR:3V3
bank{down, 1, 3, forward, Cap C1 100n, Cap C2 1u, Cap C3 10u}
```
