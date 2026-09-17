"""Lexer + parser for the Netic language (see SYNTAX.md)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple, Union


class ParseError(Exception):
    def __init__(self, message: str, line: int = 1, col: int = 1):
        super().__init__(f"{line}:{col}: {message}")
        self.line = line
        self.col = col
        self.message = message


@dataclass(frozen=True)
class Tok:
    kind: str
    value: str
    line: int
    col: int


@dataclass(frozen=True)
class Draw:
    letter: str


@dataclass(frozen=True)
class AirMove:
    letters: Tuple[str, ...]


@dataclass(frozen=True)
class TwoPin:
    kind: str
    ref: Optional[str]
    value: Optional[str]


@dataclass(frozen=True)
class Source:
    kind: str
    polarity: str
    ref: Optional[str]
    value: Optional[str]


@dataclass(frozen=True)
class Xtor:
    family: str
    pin: str
    device: Optional[str]
    ref: Optional[str]
    value: Optional[str]


@dataclass(frozen=True)
class Gnd:
    name: str = "GND"


@dataclass(frozen=True)
class Pwr:
    name: str


@dataclass(frozen=True)
class Label:
    name: str


@dataclass(frozen=True)
class AnchorDef:
    name: str


@dataclass(frozen=True)
class AnchorGo:
    name: str


@dataclass(frozen=True)
class Pull:
    direction: str
    stub: float
    kind: str
    ref: Optional[str]
    value: Optional[str]
    far_net: Optional[str]


@dataclass(frozen=True)
class BankPart:
    kind: str
    ref: Optional[str]
    value: Optional[str]


@dataclass(frozen=True)
class Bank:
    vertical: str
    stub: float
    pitch: float
    along: str
    parts: Tuple[BankPart, ...]


@dataclass(frozen=True)
class IcPinName:
    name: str
    number: Optional[str] = None


@dataclass(frozen=True)
class IcFace:
    face: str
    pins: Tuple[IcPinName, ...]


@dataclass(frozen=True)
class IcDecl:
    ref: str
    value: Optional[str]
    w: float
    h: float
    faces: Tuple[IcFace, ...]


@dataclass(frozen=True)
class IcAttach:
    ref: str
    pin: str


@dataclass(frozen=True)
class GoPin:
    ref: Optional[str]
    pin: str


@dataclass(frozen=True)
class Tap:
    body: Tuple["Cmd", ...]


Cmd = Union[
    Draw, AirMove, TwoPin, Source, Xtor, Gnd, Pwr, Label,
    AnchorDef, AnchorGo, Pull, Bank, IcDecl, IcAttach, GoPin, Tap,
]


TWO_PIN = {
    "res": "res",
    "cap": "cap",
    "ind": "ind",
    "dio": "dio",
    "led": "led",
    "sw": "sw",
    "xtal": "xtal",
}
XTOR_PIN = {
    "q": frozenset({"b", "c", "e"}),
    "m": frozenset({"g", "d", "s", "b"}),
}
DEVICE = frozenset({"npn", "pnp", "nmos", "pmos"})
MOVE_CHARS = frozenset("RLUDrlud")
FACE_ALIAS = {
    "l": "left", "left": "left",
    "r": "right", "right": "right",
    "t": "top", "top": "top",
    "b": "bottom", "bottom": "bottom",
}
COMMAND_WORDS = frozenset({
    "gnd", "pwr", "label", "net", "move", "mov",
    "pulldown", "pullup", "bank", "ic", "tap", "to", "pin",
}) | set(TWO_PIN) | {"vsrc", "isrc", "q", "m"}

_TOKEN = re.compile(
    r"(?P<ws>[ \t]+)"
    r"|(?P<nl>\n)"
    r"|(?P<comment>\#[^\n]*)"
    r"|(?P<sym>[(){}:@,])"
    r"|(?P<num>[+\-]?\d+(?:\.\d+)?[A-Za-z0-9%]*)"
    r"|(?P<ident>[A-Za-z_][A-Za-z0-9_]*)"
)


def tokenize(src: str) -> List[Tok]:
    src = src.replace("\r\n", "\n").replace("\r", "\n")
    if not src.endswith("\n"):
        src += "\n"
    out: List[Tok] = []
    line = 1
    col = 1
    i = 0
    while i < len(src):
        m = _TOKEN.match(src, i)
        if not m:
            raise ParseError(f"unexpected character {src[i]!r}", line, col)
        kind = m.lastgroup
        text = m.group()
        n = len(text)
        if kind == "nl":
            line += 1
            col = 1
            i += n
            continue
        if kind in ("ws", "comment"):
            col += n
            i += n
            continue
        if kind == "sym":
            out.append(Tok("SYM", text, line, col))
        elif kind == "num":
            out.append(Tok("NUM", text, line, col))
        else:
            if len(text) == 1 and text in MOVE_CHARS:
                out.append(Tok("MOVE", text, line, col))
            else:
                out.append(Tok("IDENT", text, line, col))
        col += n
        i += n
    out.append(Tok("EOF", "", line, col))
    return out


def _is_name(tok: Tok) -> bool:
    return tok.kind in ("IDENT", "NUM", "MOVE")


class _P:
    def __init__(self, toks: Sequence[Tok]):
        self.toks = toks
        self.i = 0

    def peek(self) -> Tok:
        return self.toks[self.i]

    def get(self) -> Tok:
        t = self.toks[self.i]
        if t.kind != "EOF":
            self.i += 1
        return t

    def eat(self, kind: str, value: Optional[str] = None) -> Tok:
        t = self.peek()
        if t.kind != kind or (value is not None and t.value != value):
            want = value if value is not None else kind
            raise ParseError(f"expected {want}, got {t.value!r}", t.line, t.col)
        return self.get()

    def parse(self) -> List[Cmd]:
        cmds: List[Cmd] = []
        while self.peek().kind != "EOF":
            cmds.append(self._cmd())
        return cmds

    def _cmd(self) -> Cmd:
        t = self.peek()
        if t.kind == "MOVE":
            return Draw(self.get().value)
        if t.kind == "SYM" and t.value == "(":
            return self._anchor_def()
        if t.kind == "SYM" and t.value == "@":
            return self._anchor_go()
        if t.kind != "IDENT":
            raise ParseError(f"unexpected token {t.value!r}", t.line, t.col)
        low = t.value.lower()
        if low in ("move", "mov"):
            return self._air()
        if low == "pulldown":
            return self._pull("down")
        if low == "pullup":
            return self._pull("up")
        if low == "bank":
            return self._bank()
        if low == "gnd":
            return self._gnd()
        if low == "pwr":
            return self._pwr()
        if low in ("label", "net"):
            return self._label()
        if low in TWO_PIN:
            return self._two_pin()
        if low in ("vsrc", "isrc"):
            return self._source()
        if low in ("q", "m"):
            return self._xtor()
        if low == "ic":
            return self._ic()
        if low == "tap":
            return self._tap()
        if low in ("to", "pin"):
            return self._go_pin()
        nxt = self.toks[self.i + 1] if self.i + 1 < len(self.toks) else None
        if nxt is not None and nxt.kind == "SYM" and nxt.value == ":":
            return self._ic_attach()
        raise ParseError(f"unknown command {t.value!r}", t.line, t.col)

    def _anchor_def(self) -> AnchorDef:
        self.eat("SYM", "(")
        name = self._name_token("anchor name")
        self.eat("SYM", ")")
        return AnchorDef(name)

    def _anchor_go(self) -> AnchorGo:
        self.eat("SYM", "@")
        name = self._name_token("anchor name")
        if self.peek().kind == "SYM" and self.peek().value == ":":
            self.get()
            name = f"{name}:{self._name_token('pin name')}"
        return AnchorGo(name)

    def _name_token(self, what: str) -> str:
        t = self.peek()
        if not _is_name(t):
            raise ParseError(f"expected {what}", t.line, t.col)
        return self.get().value

    def _gnd(self) -> Gnd:
        self.get()
        if self.peek().kind == "SYM" and self.peek().value == ":":
            self.get()
            return Gnd(self._name_token("gnd name"))
        return Gnd("GND")

    def _pwr(self) -> Pwr:
        self.get()
        if self.peek().kind != "SYM" or self.peek().value != ":":
            t = self.peek()
            raise ParseError("expected :name after PWR", t.line, t.col)
        self.get()
        return Pwr(self._name_token("power name"))

    def _label(self) -> Label:
        self.get()
        return Label(self._name_token("label name"))

    def _maybe_ref_value(self) -> Tuple[Optional[str], Optional[str]]:
        ref = None
        value = None
        t = self.peek()
        if t.kind == "IDENT" and t.value.lower() not in COMMAND_WORDS and t.value.lower() not in DEVICE:
            ref = self.get().value
            t = self.peek()
        if t.kind == "NUM":
            value = self.get().value
        elif (
            t.kind == "IDENT"
            and ref is not None
            and t.value.lower() not in COMMAND_WORDS
            and t.value.lower() not in DEVICE
        ):
            value = self.get().value
        return ref, value

    def _two_pin(self) -> TwoPin:
        kind = TWO_PIN[self.get().value.lower()]
        ref, value = self._maybe_ref_value()
        return TwoPin(kind, ref, value)

    def _source(self) -> Source:
        kind = self.get().value.lower()
        pol = "P"
        if self.peek().kind == "SYM" and self.peek().value == ":":
            self.get()
            p = self._name_token("P or N").upper()
            if p not in ("P", "N"):
                t = self.peek()
                raise ParseError(f"source polarity must be P or N, got {p!r}", t.line, t.col)
            pol = p
        ref, value = self._maybe_ref_value()
        return Source(kind, pol, ref, value)

    def _xtor(self) -> Xtor:
        fam = self.get().value.lower()
        pin = "b" if fam == "q" else "g"
        t = self.peek()
        if t.kind == "SYM" and t.value == ":":
            colon = self.get()
            pin_tok = self._name_token("pin")
            pin = pin_tok.lower()
            if pin not in XTOR_PIN[fam]:
                allow = "/".join(p.upper() for p in sorted(XTOR_PIN[fam]))
                raise ParseError(
                    f"{fam.upper()} pin must be {allow}, got {pin_tok!r}",
                    colon.line,
                    colon.col,
                )
        device = None
        t = self.peek()
        if t.kind == "IDENT" and t.value.lower() in DEVICE:
            device = self.get().value.lower()
        ref, value = self._maybe_ref_value()
        return Xtor(fam, pin, device, ref, value)

    def _air(self) -> AirMove:
        self.get()
        self.eat("SYM", "{")
        letters: List[str] = []
        while not (self.peek().kind == "SYM" and self.peek().value == "}"):
            t = self.peek()
            if t.kind == "EOF":
                raise ParseError("unclosed move {", t.line, t.col)
            if t.kind == "MOVE":
                letters.append(self.get().value)
                continue
            if t.kind == "IDENT" and all(c in MOVE_CHARS for c in t.value):
                letters.extend(list(self.get().value))
                continue
            raise ParseError(
                f"move steps must be r/l/u/d (or R/L/U/D), got {t.value!r}",
                t.line,
                t.col,
            )
        self.eat("SYM", "}")
        if not letters:
            t = self.peek()
            raise ParseError("move { } is empty", t.line, t.col)
        return AirMove(tuple(letters))

    def _pull(self, direction: str) -> Pull:
        kw = self.get()
        self.eat("SYM", "{")
        inner = self._brace_tokens()
        if not inner:
            raise ParseError("empty pull command", kw.line, kw.col)
        stub, rest = _stub_from(inner)
        if not rest:
            raise ParseError("pull needs a component", kw.line, kw.col)
        kind, ref, value, far, leftover = _part_and_net(rest)
        if leftover:
            raise ParseError(
                f"extra tokens in pull: {leftover[0].value!r}",
                leftover[0].line,
                leftover[0].col,
            )
        return Pull(direction, stub, kind, ref, value, far)

    def _bank(self) -> Bank:
        kw = self.get()
        self.eat("SYM", "{")
        inner = self._brace_tokens()
        groups = _split_comma(inner)
        if len(groups) < 5:
            raise ParseError(
                "bank needs down|up, stub, pitch, forward|backward, then parts",
                kw.line,
                kw.col,
            )
        vert = groups[0][0].value.lower()
        if vert not in ("up", "down"):
            raise ParseError("bank direction must be up or down", kw.line, kw.col)
        stub = _number(groups[1][0])
        pitch = _number(groups[2][0])
        along = groups[3][0].value.lower()
        if along not in ("forward", "backward"):
            raise ParseError("bank along must be forward or backward", kw.line, kw.col)
        parts: List[BankPart] = []
        for g in groups[4:]:
            kind, ref, value, far, leftover = _part_and_net(g)
            if far is not None:
                raise ParseError(
                    "bank parts cannot take a far net here",
                    g[0].line,
                    g[0].col,
                )
            if leftover:
                raise ParseError(
                    f"extra tokens in bank part: {leftover[0].value!r}",
                    leftover[0].line,
                    leftover[0].col,
                )
            parts.append(BankPart(kind, ref, value))
        return Bank(vert, stub, pitch, along, tuple(parts))

    def _ic(self) -> IcDecl:
        kw = self.get()
        ref_tok = self.peek()
        if ref_tok.kind != "IDENT":
            raise ParseError("IC needs a designator (U1, …)", ref_tok.line, ref_tok.col)
        if ref_tok.value.lower() in COMMAND_WORDS:
            raise ParseError(
                f"IC designator cannot be {ref_tok.value!r}",
                ref_tok.line, ref_tok.col,
            )
        ref = self.get().value
        value = None
        t = self.peek()
        size_tok = None
        if t.kind == "NUM" and _is_size_token(t.value):
            size_tok = self.get()
        elif t.kind in ("IDENT", "NUM") and t.value != "{":
            value = self.get().value
            t = self.peek()
            if t.kind == "NUM" and _is_size_token(t.value):
                size_tok = self.get()
        if size_tok is None:
            t = self.peek()
            raise ParseError(
                "IC needs a size like 3x4",
                t.line, t.col,
            )
        w, h = _parse_size(size_tok)
        self.eat("SYM", "{")
        inner = self._brace_tokens()
        faces = _parse_ic_faces(inner)
        if not faces:
            raise ParseError("IC has no pins", kw.line, kw.col)
        return IcDecl(ref, value, w, h, faces)

    def _ic_attach(self) -> IcAttach:
        ref = self.get().value
        self.eat("SYM", ":")
        pin = self._name_token("IC pin")
        return IcAttach(ref, pin)

    def _go_pin(self) -> GoPin:
        self.get()
        t = self.peek()
        if not _is_name(t):
            raise ParseError("to/pin needs a pin name", t.line, t.col)
        first = self.get().value
        if self.peek().kind == "SYM" and self.peek().value == ":":
            self.get()
            return GoPin(first, self._name_token("pin name"))
        return GoPin(None, first)

    def _tap(self) -> Tap:
        kw = self.get()
        self.eat("SYM", "{")
        body: List[Cmd] = []
        while not (self.peek().kind == "SYM" and self.peek().value == "}"):
            t = self.peek()
            if t.kind == "EOF":
                raise ParseError("unclosed tap {", t.line, t.col)
            body.append(self._cmd())
        self.eat("SYM", "}")
        if not body:
            raise ParseError("empty tap command", kw.line, kw.col)
        return Tap(tuple(body))

    def _brace_tokens(self) -> List[Tok]:
        inner: List[Tok] = []
        depth = 1
        while True:
            t = self.peek()
            if t.kind == "EOF":
                raise ParseError("unclosed {", t.line, t.col)
            if t.kind == "SYM" and t.value == "{":
                depth += 1
                inner.append(self.get())
                continue
            if t.kind == "SYM" and t.value == "}":
                depth -= 1
                if depth == 0:
                    self.get()
                    return inner
                inner.append(self.get())
                continue
            inner.append(self.get())


def _split_comma(toks: Sequence[Tok]) -> List[List[Tok]]:
    groups: List[List[Tok]] = [[]]
    for t in toks:
        if t.kind == "SYM" and t.value == ",":
            groups.append([])
        else:
            groups[-1].append(t)
    return [g for g in groups if g]


def _number(tok: Tok) -> float:
    m = re.match(r"^[+\-]?\d+(?:\.\d+)?", tok.value)
    if not m:
        raise ParseError(f"expected a number, got {tok.value!r}", tok.line, tok.col)
    return float(m.group())


def _is_size_token(text: str) -> bool:
    return bool(re.match(r"^\d+(?:\.\d+)?[xX]\d+(?:\.\d+)?$", text))


def _parse_size(tok: Tok) -> Tuple[float, float]:
    m = re.match(r"^(\d+(?:\.\d+)?)[xX](\d+(?:\.\d+)?)$", tok.value)
    if not m:
        raise ParseError(f"expected size like 3x4, got {tok.value!r}", tok.line, tok.col)
    w, h = float(m.group(1)), float(m.group(2))
    if w <= 0 or h <= 0:
        raise ParseError(f"IC size must be positive, got {tok.value!r}", tok.line, tok.col)
    return w, h


def _parse_ic_faces(toks: Sequence[Tok]) -> Tuple[IcFace, ...]:
    faces: List[IcFace] = []
    i = 0
    n = len(toks)
    while i < n:
        t = toks[i]
        low = t.value.lower()
        if t.kind == "SYM" and t.value == ",":
            i += 1
            continue
        if low not in FACE_ALIAS:
            raise ParseError(
                f"expected IC face L/R/T/B, got {t.value!r}",
                t.line, t.col,
            )
        face = FACE_ALIAS[low]
        i += 1
        if i >= n or not (toks[i].kind == "SYM" and toks[i].value == ":"):
            raise ParseError(f"expected : after {face} face", t.line, t.col)
        i += 1
        pins: List[IcPinName] = []
        while i < n:
            p = toks[i]
            if p.kind == "SYM" and p.value == ",":
                # comma may separate faces or pins; peek after comma
                if i + 1 < n and toks[i + 1].value.lower() in FACE_ALIAS:
                    break
                i += 1
                continue
            if p.value.lower() in FACE_ALIAS:
                nxt = toks[i + 1] if i + 1 < n else None
                if nxt is not None and nxt.kind == "SYM" and nxt.value == ":":
                    break
            if not _is_name(p):
                raise ParseError(f"expected pin name, got {p.value!r}", p.line, p.col)
            i += 1
            number = None
            name = p.value
            if i < n and toks[i].kind == "SYM" and toks[i].value == ":":
                i += 1
                if i >= n or not _is_name(toks[i]):
                    raise ParseError("expected pin name after number:", p.line, p.col)
                number = name
                name = toks[i].value
                i += 1
            pins.append(IcPinName(name=name, number=number))
        if not pins:
            raise ParseError(f"{face} face has no pins", t.line, t.col)
        faces.append(IcFace(face, tuple(pins)))
    return tuple(faces)


def _stub_from(toks: Sequence[Tok]) -> Tuple[float, List[Tok]]:
    if not toks:
        raise ParseError("missing stub length")
    if toks[0].kind == "NUM" or re.match(r"^[+\-]?\d", toks[0].value):
        n = _number(toks[0])
        if n < 1 or abs(n - round(n)) > 1e-9:
            raise ParseError(
                "stub length must be a positive integer",
                toks[0].line,
                toks[0].col,
            )
        return float(int(round(n))), list(toks[1:])
    raise ParseError(
        "stub length must be a positive integer", toks[0].line, toks[0].col
    )


def _looks_like_value(text: str) -> bool:
    if re.match(r"^[+\-]?\d", text):
        return True
    if re.search(r"\d", text) and text.lower() not in ("gnd", "vcc", "vdd", "vss"):
        return True
    return False


def _part_and_net(
    toks: Sequence[Tok],
) -> Tuple[str, Optional[str], Optional[str], Optional[str], List[Tok]]:
    if not toks:
        raise ParseError("expected a component")
    kind_tok = toks[0]
    low = kind_tok.value.lower()
    if low not in TWO_PIN:
        raise ParseError(
            f"expected two-pin kind, got {kind_tok.value!r}",
            kind_tok.line,
            kind_tok.col,
        )
    kind = TWO_PIN[low]
    rest = list(toks[1:])
    ref = None
    value = None
    far = None
    i = 0
    if i < len(rest) and rest[i].kind == "IDENT" and rest[i].value.lower() not in TWO_PIN:
        ref = rest[i].value
        i += 1
    if i < len(rest) and rest[i].kind == "NUM":
        value = rest[i].value
        i += 1
    elif i < len(rest) and rest[i].kind == "IDENT" and _looks_like_value(rest[i].value):
        value = rest[i].value
        i += 1
    if i < len(rest):
        far = rest[i].value
        i += 1
    return kind, ref, value, far, rest[i:]


def parse_netic(src: str) -> List[Cmd]:
    return _P(tokenize(src)).parse()
