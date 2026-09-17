"""Netic language — parser + interpreter benches."""

from __future__ import annotations

import unittest
from pathlib import Path

from netic.compile import compile_netic
from netic.parser import (
    AirMove,
    AnchorDef,
    AnchorGo,
    Bank,
    Draw,
    ParseError,
    Pull,
    Tap,
    TwoPin,
    Xtor,
    parse_netic,
)


def _pt(c, ref):
    for x in c.grid["components"]:
        if x["ref"] == ref:
            return x
    raise AssertionError(f"missing {ref} in { [x['ref'] for x in c.grid['components']] }")


class ParseTests(unittest.TestCase):
    def test_moves_and_res(self):
        cmds = parse_netic("R Res R1 10k r")
        self.assertIsInstance(cmds[0], Draw)
        self.assertEqual(cmds[0].letter, "R")
        self.assertIsInstance(cmds[1], TwoPin)
        self.assertEqual(cmds[1].kind, "res")
        self.assertEqual(cmds[1].ref, "R1")
        self.assertEqual(cmds[1].value, "10k")
        self.assertEqual(cmds[2].letter, "r")

    def test_xtor_and_move(self):
        cmds = parse_netic("r Q:B npn Q1 2N3904 move { r u }")
        self.assertIsInstance(cmds[1], Xtor)
        self.assertEqual(cmds[1].pin, "b")
        self.assertEqual(cmds[1].device, "npn")
        self.assertEqual(cmds[1].ref, "Q1")
        self.assertEqual(cmds[1].value, "2N3904")
        self.assertIsInstance(cmds[2], AirMove)
        self.assertEqual(cmds[2].letters, ("r", "u"))

    def test_mosfet_bulk_pin_parses(self):
        cmds = parse_netic("r M:B nmos M1")
        self.assertIsInstance(cmds[1], Xtor)
        self.assertEqual(cmds[1].family, "m")
        self.assertEqual(cmds[1].pin, "b")

    def test_pull_and_bank(self):
        cmds = parse_netic(
            "pulldown{1 Cap C3 100n} pullup{1 Res R2 10k VCC} "
            "bank{down, 1, 3, forward, Cap C1 100n, Cap C2 1u}"
        )
        self.assertIsInstance(cmds[0], Pull)
        self.assertEqual(cmds[0].direction, "down")
        self.assertEqual(cmds[0].stub, 1.0)
        self.assertEqual(cmds[0].kind, "cap")
        self.assertEqual(cmds[0].ref, "C3")
        self.assertEqual(cmds[0].far_net, None)
        self.assertEqual(cmds[1].far_net, "VCC")
        self.assertIsInstance(cmds[2], Bank)
        self.assertEqual(cmds[2].pitch, 3.0)
        self.assertEqual(len(cmds[2].parts), 2)

    def test_half_stub_rejected(self):
        with self.assertRaises(ParseError):
            parse_netic("pulldown{0.5 Cap C1}")

    def test_anchors(self):
        cmds = parse_netic("(n1) @n1")
        self.assertEqual(cmds[0], AnchorDef("n1"))
        self.assertEqual(cmds[1], AnchorGo("n1"))

    def test_unknown_token(self):
        with self.assertRaises(ParseError):
            parse_netic("foo bar")


class WalkTests(unittest.TestCase):
    def test_series_resistor_centers(self):
        r = compile_netic("R Res R1 10k R")
        self.assertTrue(r.ok, r.issues)
        c = _pt(r, "R1")
        self.assertEqual(c["gx"], 2.0)
        self.assertEqual(c["gy"], 0.0)
        self.assertEqual(c["w"], 2.0)
        self.assertEqual(c["h"], 2.0)
        self.assertEqual(c["orientation"], "horizontal")
        self.assertEqual(len(r.grid["wires"]), 2)

    def test_upper_and_lower_steps_match(self):
        a = compile_netic("R Res R1 10k R")
        b = compile_netic("r Res R1 10k r")
        self.assertTrue(a.ok and b.ok)
        self.assertEqual(_pt(a, "R1")["gx"], _pt(b, "R1")["gx"])
        self.assertEqual(_pt(a, "R1")["gy"], _pt(b, "R1")["gy"])

    def test_pulldown_returns_pen(self):
        r = compile_netic("R (n1) pulldown{1 Cap C1 100n} R Res R1 1k")
        self.assertTrue(r.ok, [i.to_json() for i in r.issues])
        cap = _pt(r, "C1")
        res = _pt(r, "R1")
        self.assertEqual(cap["orientation"], "vertical")
        self.assertAlmostEqual(cap["gx"], 1.0)
        self.assertAlmostEqual(cap["gy"], -2.0)
        self.assertAlmostEqual(res["gx"], 3.0)
        self.assertAlmostEqual(res["gy"], 0.0)
        gnds = [s for s in r.grid["power_symbols"] if "GND" in s["net"]]
        self.assertTrue(gnds)

    def test_anchor_resume(self):
        r = compile_netic("R (n1) D Cap C1 D GND @n1 U Res R2 U PWR:VCC")
        self.assertTrue(r.ok, [i.to_json() for i in r.issues])
        self.assertAlmostEqual(_pt(r, "C1")["gy"], -2.0)
        self.assertAlmostEqual(_pt(r, "R2")["gy"], 2.0)

    def test_body_overlap(self):
        r = compile_netic("R Res R1 R L Res R2")
        codes = [i.code for i in r.issues]
        self.assertIn("body_overlap", codes)
        self.assertFalse(r.ok)

    def test_ce_collector_air_move(self):
        r = compile_netic("r Q:B npn Q1 2N3904 move { r u } U Res Rc 1k")
        self.assertTrue(r.ok, [i.to_json() for i in r.issues])
        q = _pt(r, "Q1")
        self.assertEqual(q["kind"], "transistor")
        self.assertEqual(q["w"], 2.0)
        self.assertEqual(q["h"], 2.0)
        self.assertAlmostEqual(q["gx"], 2.0)
        self.assertAlmostEqual(q["gy"], 0.0)
        self.assertEqual(q["pin_faces"]["b"], "left")
        self.assertEqual(q["pin_faces"]["c"], "top")
        self.assertEqual(q["pin_faces"]["e"], "bottom")
        rc = _pt(r, "Rc")
        self.assertEqual(rc["orientation"], "vertical")
        self.assertAlmostEqual(rc["gx"], 2.0)
        self.assertAlmostEqual(rc["gy"], 3.0)

    def test_mosfet_bulk_on_opposite_face(self):
        r = compile_netic("r M:G nmos M1")
        self.assertTrue(r.ok, [i.to_json() for i in r.issues])
        m = _pt(r, "M1")
        self.assertEqual(m["pin_faces"]["g"], "left")
        self.assertEqual(m["pin_faces"]["d"], "top")
        self.assertEqual(m["pin_faces"]["s"], "bottom")
        self.assertEqual(m["pin_faces"]["b"], "right")
        bulk = m["pins"]["b"]
        self.assertAlmostEqual(m["gx"] + bulk["x"], 3.0)
        self.assertAlmostEqual(m["gy"] + bulk["y"], 0.0)

    def test_bank_pitch(self):
        r = compile_netic(
            "PWR:3V3 bank{down, 1, 3, forward, Cap C1 100n, Cap C2 1u, Cap C3 10u}"
        )
        self.assertTrue(r.ok, [i.to_json() for i in r.issues])
        self.assertAlmostEqual(_pt(r, "C1")["gx"], 0.0)
        self.assertAlmostEqual(_pt(r, "C2")["gx"], 3.0)
        self.assertAlmostEqual(_pt(r, "C3")["gx"], 6.0)

    def test_syntax_error_is_issue(self):
        r = compile_netic("???")
        self.assertFalse(r.ok)
        self.assertEqual(r.issues[0].code, "syntax")


CE_ORIGINAL = """\
label VIN
r Cap Cin 100n r (base)
pullup{2 Res Rb1 47k VCC}
pulldown{2 Res Rb2 10k}
r r (qb) Q:B npn Q1 2N3904
to C
(vc)
u u Res Rc 1k u PWR:VCC
@vc
r r r Cap Cout 100n r
label VOUT
@qb
to E
(ve)
d d Res Re 100 d GND
@ve
r r r r
pulldown{1 Cap Ce 10u}
"""

CE_FIXED = """\
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
"""


def _aes_codes(r) -> list:
    return sorted(i.code for i in r.issues if i.code in ("face_tangent", "rail_alignment"))


class AestheticsTests(unittest.TestCase):
    def test_face_tangent_ce_original(self):
        r = compile_netic(CE_ORIGINAL)
        self.assertTrue(r.ok, [i.to_json() for i in r.issues])
        self.assertEqual(_aes_codes(r), ["face_tangent", "face_tangent"])
        msgs = [i.message for i in r.issues]
        self.assertTrue(any("Q1 top face" in m for m in msgs))
        self.assertTrue(any("Q1 bottom face" in m for m in msgs))
        for i in r.issues:
            self.assertEqual(i.severity, "WARNING")

    def test_face_tangent_minimal(self):
        r = compile_netic("r Q:B npn Q1 move { r u } r r")
        self.assertTrue(r.ok, [i.to_json() for i in r.issues])
        self.assertEqual(_aes_codes(r), ["face_tangent"])

    def test_face_tangent_pin_contact_ok(self):
        r = compile_netic("r Q:B npn Q1 move { r u } U Res Rc 1k")
        self.assertTrue(r.ok, [i.to_json() for i in r.issues])
        self.assertNotIn("face_tangent", _aes_codes(r))

    def test_face_tangent_bank_rail_ok(self):
        r = compile_netic("PWR:3V3 bank{down, 1, 3, forward, Cap C1 100n, Cap C2 1u}")
        self.assertTrue(r.ok, [i.to_json() for i in r.issues])
        self.assertNotIn("face_tangent", _aes_codes(r))

    def test_fixed_ce_zero_aesthetics(self):
        r = compile_netic(CE_FIXED)
        self.assertTrue(r.ok, [i.to_json() for i in r.issues])
        self.assertEqual(_aes_codes(r), [])
        self.assertNotIn("body_spacing", [i.code for i in r.issues])
        cout = _pt(r, "Cout")
        self.assertEqual((cout["gx"], cout["gy"]), (10.0, 2.0))
        self.assertEqual(_pt(r, "Ce")["gy"], -4.0)
        self.assertEqual(_pt(r, "Re")["gy"], -4.0)
        vcc = sorted(s["gy"] for s in r.grid["power_symbols"] if s["net"] == "VCC")
        gnd = sorted(s["gy"] for s in r.grid["power_symbols"] if s["net"] == "GND")
        self.assertEqual(vcc, [6.0, 6.0])
        self.assertEqual(gnd, [-6.0, -6.0, -6.0])

    def test_body_spacing_touching(self):
        r = compile_netic("r Res R1 u Res R2")
        self.assertTrue(r.ok, [i.to_json() for i in r.issues])
        codes = [i.code for i in r.issues]
        self.assertIn("body_spacing", codes)

    def test_body_spacing_ok(self):
        r = compile_netic("R Res R1 R Res R2")
        self.assertTrue(r.ok, [i.to_json() for i in r.issues])
        self.assertNotIn("body_spacing", [i.code for i in r.issues])

    def test_examples_aesthetics_sweep(self):
        root = Path(__file__).resolve().parents[1]
        for name in (
            "01_rc_lpf", "02_rc_hpf", "03_lc_ladder", "04_common_emitter",
            "05_common_source", "06_source_follower", "07_colpitts", "08_wien",
            "09_diff_pair", "10_cs_lna",
        ):
            src = (root / "examples" / f"{name}.netic").read_text(encoding="utf-8")
            r = compile_netic(src)
            self.assertTrue(r.ok, f"{name}: {[i.to_json() for i in r.issues]}")
            self.assertEqual(_aes_codes(r), [], name)
            for bad in ("body_spacing", "symbol_on_pin"):
                self.assertNotIn(bad, [i.code for i in r.issues], name)

    def test_diff_pair_emitters_connected(self):
        root = Path(__file__).resolve().parents[1]
        src = (root / "examples" / "09_diff_pair.netic").read_text(encoding="utf-8")
        r = compile_netic(src)
        self.assertTrue(r.ok, [i.to_json() for i in r.issues])
        pts = set()
        for w in r.grid["wires"]:
            pts.add(tuple(w["path"][0]))
            pts.add(tuple(w["path"][1]))
        for c in r.grid["components"]:
            if c["kind"] != "transistor":
                continue
            for pin in c["pins"].values():
                abs_pt = (c["gx"] + pin["x"], c["gy"] + pin["y"])
                self.assertIn(abs_pt, pts, f"{c['ref']} pin {pin['name']} floating at {abs_pt}")


class V03LangTests(unittest.TestCase):
    def test_to_collector(self):
        r = compile_netic("r Q:B npn Q1 2N3904 to C U Res Rc 1k")
        self.assertTrue(r.ok, [i.to_json() for i in r.issues])
        q = _pt(r, "Q1")
        self.assertEqual(q["pin_faces"]["c"], "top")
        rc = _pt(r, "Rc")
        self.assertEqual(rc["orientation"], "vertical")
        self.assertAlmostEqual(rc["gx"], 2.0)
        self.assertAlmostEqual(rc["gy"], 3.0)

    def test_at_q1_c_same_as_to(self):
        a = compile_netic("r Q:B npn Q1 to C U Res Rc 1k")
        b = compile_netic("r Q:B npn Q1 @Q1:C U Res Rc 1k")
        self.assertTrue(a.ok and b.ok, [i.to_json() for i in a.issues + b.issues])
        self.assertEqual(_pt(a, "Rc")["gx"], _pt(b, "Rc")["gx"])
        self.assertEqual(_pt(a, "Rc")["gy"], _pt(b, "Rc")["gy"])

    def test_tap_restores_pen(self):
        r = compile_netic("R (n1) tap { D Cap C1 100n D GND } R Res R1 1k")
        self.assertTrue(r.ok, [i.to_json() for i in r.issues])
        cap = _pt(r, "C1")
        res = _pt(r, "R1")
        self.assertEqual(cap["orientation"], "vertical")
        self.assertAlmostEqual(res["gx"], 3.0)
        self.assertAlmostEqual(res["gy"], 0.0)
        self.assertIsInstance(parse_netic("tap { d GND }")[0], Tap)


def main() -> int:
    import sys

    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=2))
