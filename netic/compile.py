"""Walk a Netic program onto the grid. No placer heuristics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .parser import (
    AirMove,
    AnchorDef,
    AnchorGo,
    Bank,
    BankPart,
    Cmd,
    Draw,
    Gnd,
    GoPin,
    IcAttach,
    IcDecl,
    Label,
    ParseError,
    Pull,
    Pwr,
    Source,
    Tap,
    TwoPin,
    Xtor,
    parse_netic,
)


Point = Tuple[float, float]
# Every step is one integer grid. Uppercase and lowercase letters are aliases.
VEC = {
    "R": (1.0, 0.0),
    "r": (1.0, 0.0),
    "L": (-1.0, 0.0),
    "l": (-1.0, 0.0),
    "U": (0.0, 1.0),
    "u": (0.0, 1.0),
    "D": (0.0, -1.0),
    "d": (0.0, -1.0),
}
BODY_SIZE = 2.0
MIN_BODY_GAP = 1.0
MIN_BANK_PITCH = 3.0
HEADING_FROM_LETTER = {
    "R": (1.0, 0.0),
    "r": (1.0, 0.0),
    "L": (-1.0, 0.0),
    "l": (-1.0, 0.0),
    "U": (0.0, 1.0),
    "u": (0.0, 1.0),
    "D": (0.0, -1.0),
    "d": (0.0, -1.0),
}
KIND_RENDER = {
    "res": "resistor",
    "cap": "cap",
    "ind": "inductor",
    "dio": "other",
    "led": "led",
    "sw": "switch",
    "xtal": "crystal",
    "vsrc": "other",
    "isrc": "other",
    "q": "transistor",
    "m": "transistor",
    "ic": "ic",
}
KIND_PREFIX = {
    "res": "R",
    "cap": "C",
    "ind": "L",
    "dio": "D",
    "led": "D",
    "sw": "S",
    "xtal": "Y",
    "vsrc": "V",
    "isrc": "I",
    "q": "Q",
    "m": "M",
    "ic": "U",
}
FACE_DELTA = {
    "left": (-1.0, 0.0),
    "right": (1.0, 0.0),
    "top": (0.0, 1.0),
    "bottom": (0.0, -1.0),
}


def _snap(x: float) -> float:
    return float(round(float(x)))


def _pt(x: float, y: float) -> Point:
    return (_snap(x), _snap(y))


def _add(a: Point, b: Tuple[float, float]) -> Point:
    return _pt(a[0] + b[0], a[1] + b[1])


def _eq(a: Point, b: Point, eps: float = 1e-9) -> bool:
    return abs(a[0] - b[0]) < eps and abs(a[1] - b[1]) < eps


def _letter_len(letter: str) -> float:
    return 1.0


def _orient(heading: Tuple[float, float]) -> str:
    return "horizontal" if abs(heading[0]) > abs(heading[1]) else "vertical"


def _arrival_face(heading: Tuple[float, float]) -> str:
    dx, dy = heading
    if dx > 0:
        return "left"
    if dx < 0:
        return "right"
    if dy > 0:
        return "bottom"
    return "top"


def _far_face(heading: Tuple[float, float]) -> str:
    opp = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}
    return opp[_arrival_face(heading)]


def _ccw(face: str) -> str:
    return {"left": "bottom", "bottom": "right", "right": "top", "top": "left"}[face]


def _facing_from_heading(heading: Tuple[float, float]) -> str:
    dx, dy = heading
    if dy < 0:
        return "down"
    if dy > 0:
        return "up"
    if dx > 0:
        return "right"
    return "left"


def _outward_heading(face: str) -> Tuple[float, float]:
    return {
        "left": (-1.0, 0.0),
        "right": (1.0, 0.0),
        "top": (0.0, 1.0),
        "bottom": (0.0, -1.0),
    }[face]


def _ic_pin_offsets(w: float, h: float, face: str, n: int) -> List[Tuple[float, float]]:
    """Pin offsets from body centre; 1.0 pitch, centred on the face."""
    if n <= 0:
        return []
    if face in ("left", "right"):
        x = -w / 2.0 if face == "left" else w / 2.0
        start = (n - 1) / 2.0
        return [(_snap(x), _snap(start - i)) for i in range(n)]
    y = h / 2.0 if face == "top" else -h / 2.0
    start = -(n - 1) / 2.0
    return [(_snap(start + i), _snap(y)) for i in range(n)]


@dataclass
class Issue:
    severity: str
    code: str
    message: str
    at: Optional[Point] = None

    def to_json(self) -> dict:
        d = {"severity": self.severity, "code": self.code, "message": self.message}
        if self.at is not None:
            d["at"] = [self.at[0], self.at[1]]
        return d


@dataclass
class Body:
    ref: str
    kind: str
    gx: float
    gy: float
    w: float
    h: float
    value: str = ""
    orientation: str = "horizontal"
    device_type: Optional[str] = None
    pin_faces: Dict[str, str] = field(default_factory=dict)
    pins: Dict[str, Point] = field(default_factory=dict)


@dataclass
class Seg:
    a: Point
    b: Point
    ink: bool


@dataclass
class CompileResult:
    ok: bool
    grid: dict
    issues: List[Issue]
    source: str

    def errors(self) -> List[Issue]:
        return [i for i in self.issues if i.severity == "ERROR"]


class _UF:
    def __init__(self) -> None:
        self.p: Dict[Point, Point] = {}

    def add(self, p: Point) -> None:
        self.p.setdefault(p, p)

    def find(self, p: Point) -> Point:
        self.add(p)
        if self.p[p] != p:
            self.p[p] = self.find(self.p[p])
        return self.p[p]

    def union(self, a: Point, b: Point) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


class Engine:
    def __init__(self) -> None:
        self.x = 0.0
        self.y = 0.0
        self.heading: Optional[Tuple[float, float]] = None
        self.last_h: Tuple[float, float] = (1.0, 0.0)
        self.anchors: Dict[str, Tuple[Point, Optional[Tuple[float, float]], Tuple[float, float]]] = {}
        self.bodies: List[Body] = []
        self.segs: List[Seg] = []
        self.names: Dict[Point, str] = {}
        self.symbols: List[dict] = []
        self.issues: List[Issue] = []
        self.used_refs: Dict[str, str] = {}
        self.counters: Dict[str, int] = {}
        self.ic_decls: Dict[str, IcDecl] = {}
        self.ic_placed: Dict[str, Body] = {}

    @property
    def pos(self) -> Point:
        return _pt(self.x, self.y)

    def _need_heading(self, what: str) -> Tuple[float, float]:
        if self.heading is None:
            self.issues.append(Issue(
                "ERROR", "no_heading",
                f"{what} needs a heading — draw r/l/u/d first",
                self.pos,
            ))
            return (1.0, 0.0)
        return self.heading

    def _set_heading(self, letter: str) -> Tuple[float, float]:
        h = HEADING_FROM_LETTER[letter]
        self.heading = h
        if abs(h[0]) > 0:
            self.last_h = h
        return h

    def _alloc_ref(self, kind: str, ref: Optional[str]) -> str:
        if ref:
            if ref in self.used_refs:
                self.issues.append(Issue(
                    "ERROR", "dup_ref",
                    f"duplicate designator {ref}",
                    self.pos,
                ))
            self.used_refs[ref] = kind
            return ref
        prefix = KIND_PREFIX[kind]
        n = self.counters.get(prefix, 0) + 1
        while f"{prefix}{n}" in self.used_refs:
            n += 1
        self.counters[prefix] = n
        name = f"{prefix}{n}"
        self.used_refs[name] = kind
        return name

    def _stub_steps(self, stub: float) -> int:
        if stub < 1 or abs(stub - round(stub)) > 1e-9:
            self.issues.append(Issue(
                "ERROR", "bad_stub",
                f"stub must be a positive integer, got {stub}",
                self.pos,
            ))
            return 1
        return int(round(stub))

    def _name_point(self, p: Point, name: str) -> None:
        prev = self.names.get(p)
        if prev and prev != name:
            self.issues.append(Issue(
                "ERROR", "net_conflict",
                f"point {p} already named {prev}, cannot also be {name}",
                p,
            ))
            return
        self.names[p] = name

    def draw_letter(self, letter: str) -> None:
        dx, dy = VEC[letter]
        a = self.pos
        self._set_heading(letter)
        self.x += dx
        self.y += dy
        b = self.pos
        self.segs.append(Seg(a, b, True))

    def air_letter(self, letter: str) -> None:
        dx, dy = VEC[letter]
        a = self.pos
        self._set_heading(letter)
        self.x += dx
        self.y += dy
        b = self.pos
        self.segs.append(Seg(a, b, False))

    def _place_two_pin(self, kind: str, ref: Optional[str], value: Optional[str], length: float = BODY_SIZE) -> Body:
        h = self._need_heading(kind)
        near = self.pos
        center = _add(near, (h[0] * length / 2.0, h[1] * length / 2.0))
        far = _add(near, (h[0] * length, h[1] * length))
        w = h_sz = BODY_SIZE
        body = Body(
            ref=self._alloc_ref(kind, ref),
            kind=kind,
            gx=center[0],
            gy=center[1],
            w=w,
            h=h_sz,
            value=value or "",
            orientation=_orient(h),
            pins={"1": near, "2": far},
        )
        if kind in ("dio", "led"):
            body.pin_faces = {"A": _arrival_face(h), "K": _far_face(h)}
            body.pins = {"A": near, "K": far}
        else:
            body.pin_faces = {"1": _arrival_face(h), "2": _far_face(h)}
        self._add_body(body)
        self._register_pins(body)
        self.x, self.y = far
        return body

    def _xtor_faces(self, heading: Tuple[float, float], family: str, pin: str) -> Dict[str, str]:
        arrival = _arrival_face(heading)
        if abs(heading[0]) > 0:
            plus, minus = "top", "bottom"
        else:
            plus, minus = "right", "left"
        opp = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}
        if family == "q":
            faces = {"b": arrival, "c": plus, "e": minus}
        else:
            # MOSFET: bulk sits on the remaining face (opposite the gate).
            faces = {"g": arrival, "d": plus, "s": minus, "b": opp[arrival]}
        guard = 0
        while faces[pin] != arrival and guard < 4:
            faces = {k: _ccw(v) for k, v in faces.items()}
            guard += 1
        return faces

    def _place_xtor(self, cmd: Xtor) -> Body:
        h = self._need_heading("transistor")
        arrival = self.pos
        length = BODY_SIZE
        center = _add(arrival, (h[0] * length / 2.0, h[1] * length / 2.0))
        faces = self._xtor_faces(h, cmd.family, cmd.pin)
        pins = {
            name: _add(center, FACE_DELTA[face])
            for name, face in faces.items()
        }
        default_dev = "npn" if cmd.family == "q" else "nmos"
        body = Body(
            ref=self._alloc_ref(cmd.family, cmd.ref),
            kind=cmd.family,
            gx=center[0],
            gy=center[1],
            w=BODY_SIZE,
            h=BODY_SIZE,
            value=cmd.value or "",
            orientation=_orient(h),
            device_type=cmd.device or default_dev,
            pin_faces=faces,
            pins=pins,
        )
        self._add_body(body)
        self._register_pins(body)
        return body

    def _register_pins(self, body: Body) -> None:
        """Auto-anchors ``REF:PIN`` at each pin, heading pointing off the face."""
        for name, pt in body.pins.items():
            face = body.pin_faces.get(name)
            if face:
                heading: Optional[Tuple[float, float]] = _outward_heading(face)
            else:
                heading = self.heading
            last_h = self.last_h
            if heading is not None and abs(heading[0]) > 0:
                last_h = heading
            rec = (pt, heading, last_h)
            self.anchors[f"{body.ref}:{name}"] = rec
            if name.upper() != name:
                self.anchors[f"{body.ref}:{name.upper()}"] = rec
            if name.lower() != name:
                self.anchors[f"{body.ref}:{name.lower()}"] = rec

    def _add_body(self, body: Body) -> None:
        for other in self.bodies:
            if _bodies_overlap(body, other):
                self.issues.append(Issue(
                    "ERROR", "body_overlap",
                    f"{body.ref} overlaps {other.ref}",
                    (_snap(body.gx), _snap(body.gy)),
                ))
        self.bodies.append(body)

    def pull(self, cmd: Pull) -> None:
        saved = (self.x, self.y, self.heading, self.last_h)
        letter = "u" if cmd.direction == "up" else "d"
        n = self._stub_steps(cmd.stub)
        for _ in range(n):
            self.draw_letter(letter)
        self._place_two_pin(cmd.kind, cmd.ref, cmd.value, BODY_SIZE)
        for _ in range(n):
            self.draw_letter(letter)
        far = cmd.far_net
        if cmd.direction == "down":
            far = far or "GND"
            self._place_term(far, is_gnd=far.upper().startswith("GND") or far.upper().startswith("VSS"))
        else:
            if not far:
                self.issues.append(Issue(
                    "ERROR", "pullup_net",
                    "pullup needs a far net (VCC, 3V3, ...)",
                    self.pos,
                ))
            else:
                self._place_term(far, is_gnd=False)
        self.x, self.y, self.heading, self.last_h = saved

    def _place_term(self, name: str, *, is_gnd: bool) -> None:
        p = self.pos
        self._name_point(p, name)
        facing = _facing_from_heading(self.heading or (0.0, -1.0))
        orient = "vertical" if facing in ("up", "down") else "horizontal"
        self.symbols.append({
            "net": name,
            "gx": p[0],
            "gy": p[1],
            "facing": facing,
            "orientation": orient,
            "kind": "gnd" if is_gnd else "pwr",
        })

    def bank(self, cmd: Bank) -> None:
        saved = (self.x, self.y, self.heading, self.last_h)
        origin = self.pos
        hx, hy = self.last_h
        if cmd.along == "backward":
            hx, hy = -hx, -hy
        if cmd.pitch < MIN_BANK_PITCH or abs(cmd.pitch - round(cmd.pitch)) > 1e-9:
            self.issues.append(Issue(
                "ERROR", "bank_pitch",
                f"bank pitch must be an integer >= {MIN_BANK_PITCH:g}, got {cmd.pitch}",
                origin,
            ))
        hang_points: List[Point] = []
        for i in range(len(cmd.parts)):
            hang_points.append(_add(origin, (hx * cmd.pitch * i, hy * cmd.pitch * i)))
        for a, b in zip(hang_points, hang_points[1:]):
            self.segs.append(Seg(a, b, True))
        letter = "u" if cmd.vertical == "up" else "d"
        n = self._stub_steps(cmd.stub)
        for hang, part in zip(hang_points, cmd.parts):
            self.x, self.y = hang
            self.heading = (hx, hy)
            for _ in range(n):
                self.draw_letter(letter)
            self._place_two_pin(part.kind, part.ref, part.value, BODY_SIZE)
            for _ in range(n):
                self.draw_letter(letter)
            if cmd.vertical == "down":
                self._place_term("GND", is_gnd=True)
        self.x, self.y, self.heading, self.last_h = saved

    def _ic_layout(self, decl: IcDecl) -> Dict[str, Tuple[str, Point]]:
        """Map pin name (and number) → (face, offset from centre)."""
        out: Dict[str, Tuple[str, Point]] = {}
        for face_spec in decl.faces:
            n = len(face_spec.pins)
            offsets = _ic_pin_offsets(decl.w, decl.h, face_spec.face, n)
            for pin, off in zip(face_spec.pins, offsets):
                rec = (face_spec.face, off)
                out[pin.name] = rec
                out[pin.name.upper()] = rec
                out[pin.name.lower()] = rec
                if pin.number:
                    out[pin.number] = rec
        return out

    def _decl_ic(self, cmd: IcDecl) -> None:
        if cmd.ref in self.ic_decls:
            self.issues.append(Issue(
                "ERROR", "dup_ref",
                f"duplicate IC declaration {cmd.ref}",
                self.pos,
            ))
            return
        for face_spec in cmd.faces:
            n = len(face_spec.pins)
            if face_spec.face in ("left", "right") and n > cmd.h + 1e-9:
                self.issues.append(Issue(
                    "ERROR", "ic_pins",
                    f"{cmd.ref} {face_spec.face} has {n} pins but height is {cmd.h}",
                    self.pos,
                ))
            if face_spec.face in ("top", "bottom") and n > cmd.w + 1e-9:
                self.issues.append(Issue(
                    "ERROR", "ic_pins",
                    f"{cmd.ref} {face_spec.face} has {n} pins but width is {cmd.w}",
                    self.pos,
                ))
        self.ic_decls[cmd.ref] = cmd
        if cmd.ref in self.used_refs:
            self.issues.append(Issue(
                "ERROR", "dup_ref",
                f"duplicate designator {cmd.ref}",
                self.pos,
            ))
        else:
            self.used_refs[cmd.ref] = "ic"

    def _resolve_ic_pin(self, decl: IcDecl, pin: str) -> Optional[Tuple[str, Point]]:
        layout = self._ic_layout(decl)
        return layout.get(pin) or layout.get(pin.upper()) or layout.get(pin.lower())

    def _place_ic(self, decl: IcDecl, pin: str) -> Optional[Body]:
        h = self._need_heading("IC")
        arrival = _arrival_face(h)
        spec = self._resolve_ic_pin(decl, pin)
        if spec is None:
            self.issues.append(Issue(
                "ERROR", "unknown_pin",
                f"{decl.ref} has no pin {pin!r}",
                self.pos,
            ))
            return None
        face, offset = spec
        if face != arrival:
            self.issues.append(Issue(
                "ERROR", "ic_pin_face",
                f"walking onto {decl.ref}:{pin} ({face} face) from the "
                f"{arrival} — approach that face orthogonally",
                self.pos,
            ))
        gx = _snap(self.x - offset[0])
        gy = _snap(self.y - offset[1])
        pins: Dict[str, Point] = {}
        pin_faces: Dict[str, str] = {}
        seen = set()
        for face_spec in decl.faces:
            offs = _ic_pin_offsets(decl.w, decl.h, face_spec.face, len(face_spec.pins))
            for p, off in zip(face_spec.pins, offs):
                if p.name in seen:
                    continue
                seen.add(p.name)
                pins[p.name] = _pt(gx + off[0], gy + off[1])
                pin_faces[p.name] = face_spec.face
        body = Body(
            ref=decl.ref,
            kind="ic",
            gx=gx,
            gy=gy,
            w=decl.w,
            h=decl.h,
            value=decl.value or "",
            orientation="horizontal",
            pin_faces=pin_faces,
            pins=pins,
        )
        self._add_body(body)
        self._register_pins(body)
        self.ic_placed[decl.ref] = body
        return body

    def _attach_ic(self, cmd: IcAttach) -> None:
        decl = self.ic_decls.get(cmd.ref)
        if decl is None:
            self.issues.append(Issue(
                "ERROR", "unknown_ic",
                f"unknown IC {cmd.ref!r} — declare it with IC {cmd.ref} WxH {{ … }} first",
                self.pos,
            ))
            return
        if cmd.ref not in self.ic_placed:
            self._place_ic(decl, cmd.pin)
            return
        body = self.ic_placed[cmd.ref]
        spec = self._resolve_ic_pin(decl, cmd.pin)
        if spec is None:
            self.issues.append(Issue(
                "ERROR", "unknown_pin",
                f"{cmd.ref} has no pin {cmd.pin!r}",
                self.pos,
            ))
            return
        target = None
        for name, pt in body.pins.items():
            if name.lower() == cmd.pin.lower():
                target = pt
                break
        if target is None:
            self.issues.append(Issue(
                "ERROR", "unknown_pin",
                f"{cmd.ref} has no pin {cmd.pin!r}",
                self.pos,
            ))
            return
        if not _eq(self.pos, target):
            self.issues.append(Issue(
                "ERROR", "ic_pin_miss",
                f"pen is not on {cmd.ref}:{cmd.pin} (at {target}); use @{cmd.ref}:{cmd.pin}",
                self.pos,
            ))

    def _go_pin(self, cmd: GoPin) -> None:
        if cmd.ref:
            keys = (
                f"{cmd.ref}:{cmd.pin}",
                f"{cmd.ref}:{cmd.pin.upper()}",
                f"{cmd.ref}:{cmd.pin.lower()}",
            )
            rec = None
            for k in keys:
                if k in self.anchors:
                    rec = self.anchors[k]
                    break
            if rec is None:
                self.issues.append(Issue(
                    "ERROR", "unknown_pin",
                    f"unknown pin {cmd.ref}:{cmd.pin}",
                    self.pos,
                ))
                return
            (x, y), h, lh = rec
            self.x, self.y = x, y
            self.heading = h
            self.last_h = lh
            return
        body = self._body_at_pen()
        if body is None:
            self.issues.append(Issue(
                "ERROR", "to_pin",
                f"to {cmd.pin} — pen is not on a component pin",
                self.pos,
            ))
            return
        key = f"{body.ref}:{cmd.pin}"
        rec = (
            self.anchors.get(key)
            or self.anchors.get(f"{body.ref}:{cmd.pin.upper()}")
            or self.anchors.get(f"{body.ref}:{cmd.pin.lower()}")
        )
        if rec is None:
            self.issues.append(Issue(
                "ERROR", "unknown_pin",
                f"{body.ref} has no pin {cmd.pin!r}",
                self.pos,
            ))
            return
        (x, y), h, lh = rec
        self.x, self.y = x, y
        self.heading = h
        self.last_h = lh

    def _body_at_pen(self) -> Optional[Body]:
        p = self.pos
        for body in reversed(self.bodies):
            for pt in body.pins.values():
                if _eq(p, pt):
                    return body
        return None

    def tap(self, cmd: Tap) -> None:
        saved = (self.x, self.y, self.heading, self.last_h)
        self.run(cmd.body)
        self.x, self.y, self.heading, self.last_h = saved

    def run(self, cmds: Sequence[Cmd]) -> None:
        for cmd in cmds:
            if isinstance(cmd, Draw):
                self.draw_letter(cmd.letter)
            elif isinstance(cmd, AirMove):
                for letter in cmd.letters:
                    self.air_letter(letter)
            elif isinstance(cmd, TwoPin):
                self._place_two_pin(cmd.kind, cmd.ref, cmd.value, BODY_SIZE)
            elif isinstance(cmd, Source):
                body = self._place_two_pin(cmd.kind, cmd.ref, cmd.value, BODY_SIZE)
                body.pin_faces = {
                    "P": _arrival_face(self.heading or (1.0, 0.0)) if cmd.polarity == "P" else _far_face(self.heading or (1.0, 0.0)),
                    "N": _far_face(self.heading or (1.0, 0.0)) if cmd.polarity == "P" else _arrival_face(self.heading or (1.0, 0.0)),
                }
            elif isinstance(cmd, Xtor):
                self._place_xtor(cmd)
            elif isinstance(cmd, Gnd):
                self._place_term(cmd.name, is_gnd=True)
            elif isinstance(cmd, Pwr):
                self._place_term(cmd.name, is_gnd=False)
            elif isinstance(cmd, Label):
                self._name_point(self.pos, cmd.name)
            elif isinstance(cmd, AnchorDef):
                self.anchors[cmd.name] = (self.pos, self.heading, self.last_h)
            elif isinstance(cmd, AnchorGo):
                rec = self.anchors.get(cmd.name)
                if rec is None and ":" in cmd.name:
                    ref, _, pin = cmd.name.partition(":")
                    rec = (
                        self.anchors.get(f"{ref}:{pin}")
                        or self.anchors.get(f"{ref}:{pin.upper()}")
                        or self.anchors.get(f"{ref}:{pin.lower()}")
                    )
                if rec is None:
                    self.issues.append(Issue(
                        "ERROR", "unknown_anchor",
                        f"unknown anchor {cmd.name!r}",
                        self.pos,
                    ))
                else:
                    (x, y), h, lh = rec
                    self.x, self.y = x, y
                    self.heading = h
                    self.last_h = lh
            elif isinstance(cmd, Pull):
                self.pull(cmd)
            elif isinstance(cmd, Bank):
                self.bank(cmd)
            elif isinstance(cmd, IcDecl):
                self._decl_ic(cmd)
            elif isinstance(cmd, IcAttach):
                self._attach_ic(cmd)
            elif isinstance(cmd, GoPin):
                self._go_pin(cmd)
            elif isinstance(cmd, Tap):
                self.tap(cmd)

    def check_wires(self) -> None:
        for seg in self.segs:
            if not seg.ink:
                continue
            for body in self.bodies:
                if _seg_through_body(seg.a, seg.b, body):
                    self.issues.append(Issue(
                        "ERROR", "wire_through_body",
                        f"wire through {body.ref}",
                        seg.a,
                    ))
        ink = [s for s in self.segs if s.ink]
        for i, a in enumerate(ink):
            for b in ink[i + 1:]:
                cross = _seg_cross_mid(a.a, a.b, b.a, b.b)
                if cross is None:
                    continue
                self.issues.append(Issue(
                    "WARNING", "wire_cross",
                    "wires cross off-junction",
                    cross,
                ))

    def check_aesthetics(self) -> None:
        """Aesthetic (non-blocking) warnings: face-tangent wires, body spacing."""
        for seg in self.segs:
            if not seg.ink:
                continue
            for body in self.bodies:
                hit = _seg_tangent_to_face(seg, body)
                if hit is None:
                    continue
                face, mid = hit
                self.issues.append(Issue(
                    "WARNING", "face_tangent",
                    f"wire runs along {body.ref} {face} face — branch from the middle of a stem, not the component face",
                    mid,
                ))
        for i, a in enumerate(self.bodies):
            for b in self.bodies[i + 1:]:
                d = _body_edge_gap(a, b)
                if d is not None and d < MIN_BODY_GAP - 1e-9:
                    self.issues.append(Issue(
                        "WARNING", "body_spacing",
                        f"{a.ref} and {b.ref} too close (edge gap {d:.1f}) — keep at least {MIN_BODY_GAP:g} grid edge-to-edge",
                        (_snap(a.gx), _snap(a.gy)),
                    ))
        for s in self.symbols:
            p = _pt(s["gx"], s["gy"])
            for body in self.bodies:
                if body.kind in ("q", "m"):
                    continue  # rail symbol directly on a transistor pin is fine
                if any(abs(p[0] - pt[0]) < 1e-6 and abs(p[1] - pt[1]) < 1e-6
                       for pt in body.pins.values()):
                    self.issues.append(Issue(
                        "WARNING", "symbol_on_pin",
                        f"{s['net']} symbol sits on {body.ref} pin — leave a stub of wire between the part and its symbol",
                        p,
                    ))
                    break

    def to_grid(self, title: str) -> dict:
        uf = _UF()
        for seg in self.segs:
            if seg.ink:
                uf.union(seg.a, seg.b)
        pin_pts: List[Tuple[str, str, Point]] = []
        for body in self.bodies:
            for pname, pt in body.pins.items():
                uf.add(pt)
                pin_pts.append((body.ref, pname, pt))
        for p in self.names:
            uf.add(p)
        for s in self.symbols:
            uf.add(_pt(s["gx"], s["gy"]))

        root_name: Dict[Point, str] = {}
        for p, name in self.names.items():
            r = uf.find(p)
            prev = root_name.get(r)
            if prev and prev != name:
                self.issues.append(Issue(
                    "ERROR", "net_conflict",
                    f"nets {prev} and {name} shorted",
                    p,
                ))
            else:
                root_name[r] = name

        n_auto = 1
        net_of: Dict[Point, str] = {}

        def net_for(p: Point) -> str:
            nonlocal n_auto
            r = uf.find(p)
            if r in root_name:
                return root_name[r]
            if r not in net_of:
                net_of[r] = f"N{n_auto}"
                n_auto += 1
            return net_of[r]

        wires = []
        for seg in self.segs:
            if not seg.ink:
                continue
            if _eq(seg.a, seg.b):
                continue
            wires.append({
                "net": net_for(seg.a),
                "path": [[seg.a[0], seg.a[1]], [seg.b[0], seg.b[1]]],
            })

        comps = []
        for body in self.bodies:
            comps.append({
                "ref": body.ref,
                "gx": body.gx,
                "gy": body.gy,
                "w": body.w,
                "h": body.h,
                "kind": KIND_RENDER[body.kind],
                "value": body.value,
                "orientation": body.orientation,
                "device_type": body.device_type,
                "pin_faces": body.pin_faces,
                "pins": {
                    k: {
                        "x": v[0] - body.gx,
                        "y": v[1] - body.gy,
                        "name": k,
                        "face": body.pin_faces.get(k, ""),
                    }
                    for k, v in body.pins.items()
                },
            })

        labels = []
        seen_lab = set()
        for p, name in self.names.items():
            if any(abs(s["gx"] - p[0]) < 1e-9 and abs(s["gy"] - p[1]) < 1e-9 and s["net"] == name for s in self.symbols):
                continue
            key = (p, name)
            if key in seen_lab:
                continue
            seen_lab.add(key)
            labels.append({
                "net": name,
                "text": name,
                "stubs": [{"path": [[p[0], p[1]], [p[0], p[1]]]}],
            })

        return {
            "components": comps,
            "wires": wires,
            "power_symbols": self.symbols,
            "labels": labels,
            "meta": {
                "board": title,
                "sheet": title,
                "source": "netic",
            },
        }


def _body_edge_gap(a: Body, b: Body) -> Optional[float]:
    """Edge-to-edge distance between two bodies; None if they overlap."""
    ax0, ax1 = a.gx - a.w / 2, a.gx + a.w / 2
    ay0, ay1 = a.gy - a.h / 2, a.gy + a.h / 2
    bx0, bx1 = b.gx - b.w / 2, b.gx + b.w / 2
    by0, by1 = b.gy - b.h / 2, b.gy + b.h / 2
    if ax0 < bx1 and ax1 > bx0 and ay0 < by1 and ay1 > by0:
        return None
    dx = max(ax0 - bx1, bx0 - ax1, 0.0)
    dy = max(ay0 - by1, by0 - ay1, 0.0)
    return (dx * dx + dy * dy) ** 0.5


def _bodies_overlap(a: Body, b: Body, eps: float = 0.05) -> bool:
    ax0, ax1 = a.gx - a.w / 2, a.gx + a.w / 2
    ay0, ay1 = a.gy - a.h / 2, a.gy + a.h / 2
    bx0, bx1 = b.gx - b.w / 2, b.gx + b.w / 2
    by0, by1 = b.gy - b.h / 2, b.gy + b.h / 2
    return ax0 < bx1 - eps and ax1 > bx0 + eps and ay0 < by1 - eps and ay1 > by0 + eps


def _pt_in_body_interior(p: Point, body: Body, eps: float = 0.05) -> bool:
    return (
        abs(p[0] - body.gx) < body.w / 2 - eps
        and abs(p[1] - body.gy) < body.h / 2 - eps
    )


def _on_face(p: Point, body: Body, eps: float = 0.15) -> bool:
    for pt in body.pins.values():
        if abs(p[0] - pt[0]) < eps and abs(p[1] - pt[1]) < eps:
            return True
    return False


def _seg_through_body(a: Point, b: Point, body: Body) -> bool:
    samples = 8
    for i in range(1, samples):
        t = i / samples
        p = _pt(a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        if _pt_in_body_interior(p, body) and not _on_face(p, body):
            return True
    return False


def _seg_tangent_to_face(seg: Seg, body: Body, eps: float = 0.1) -> Optional[Tuple[str, Point]]:
    """If an axis-aligned ink seg runs along a body face edge for more than eps
    grid units, return (face, overlap_midpoint); else None."""
    x0, y0 = seg.a
    x1, y1 = seg.b
    fx0, fx1 = body.gx - body.w / 2, body.gx + body.w / 2
    fy0, fy1 = body.gy - body.h / 2, body.gy + body.h / 2
    if abs(y1 - y0) < 1e-9 and abs(x1 - x0) > 1e-9:
        lo, hi = (x0, x1) if x0 < x1 else (x1, x0)
        for face, fy in (("top", fy1), ("bottom", fy0)):
            if abs(y0 - fy) < 1e-9:
                ov = min(hi, fx1) - max(lo, fx0)
                if ov > eps:
                    return face, (max(lo, fx0) + ov / 2.0, y0)
    elif abs(x1 - x0) < 1e-9 and abs(y1 - y0) > 1e-9:
        lo, hi = (y0, y1) if y0 < y1 else (y1, y0)
        for face, fx in (("right", fx1), ("left", fx0)):
            if abs(x0 - fx) < 1e-9:
                ov = min(hi, fy1) - max(lo, fy0)
                if ov > eps:
                    return face, (x0, max(lo, fy0) + ov / 2.0)
    return None


def _seg_cross_mid(a1: Point, a2: Point, b1: Point, b2: Point) -> Optional[Point]:
    """Axis-aligned mid-span cross (not sharing an endpoint)."""
    def horiz(p, q):
        return abs(p[1] - q[1]) < 1e-9 and abs(p[0] - q[0]) > 1e-9

    def vert(p, q):
        return abs(p[0] - q[0]) < 1e-9 and abs(p[1] - q[1]) > 1e-9

    ah, av = horiz(a1, a2), vert(a1, a2)
    bh, bv = horiz(b1, b2), vert(b1, b2)
    if ah and bv:
        y = a1[1]
        x = b1[0]
        if _between(x, a1[0], a2[0]) and _between(y, b1[1], b2[1]):
            if not _is_end(x, y, a1, a2) and not _is_end(x, y, b1, b2):
                return _pt(x, y)
    if av and bh:
        x = a1[0]
        y = b1[1]
        if _between(y, a1[1], a2[1]) and _between(x, b1[0], b2[0]):
            if not _is_end(x, y, a1, a2) and not _is_end(x, y, b1, b2):
                return _pt(x, y)
    return None


def _between(v: float, a: float, b: float, eps: float = 1e-9) -> bool:
    lo, hi = (a, b) if a < b else (b, a)
    return lo + eps < v < hi - eps


def _is_end(x: float, y: float, a: Point, b: Point) -> bool:
    return (_eq((x, y), a) or _eq((x, y), b))


def compile_netic(src: str, *, title: str = "netic") -> CompileResult:
    try:
        cmds = parse_netic(src)
    except ParseError as e:
        issue = Issue("ERROR", "syntax", str(e))
        return CompileResult(
            ok=False,
            grid={"components": [], "wires": [], "power_symbols": [], "labels": [], "meta": {"board": title}},
            issues=[issue],
            source=src,
        )
    eng = Engine()
    eng.run(cmds)
    eng.check_wires()
    eng.check_aesthetics()
    grid = eng.to_grid(title)
    errors = [i for i in eng.issues if i.severity == "ERROR"]
    return CompileResult(ok=not errors, grid=grid, issues=eng.issues, source=src)
