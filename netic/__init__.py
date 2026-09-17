"""Netic — relative grid-space analog schematic language.

LLM writes ``*.netic`` text. This package parses, walks the cursor,
checks overlaps, and emits grid-space JSON / HTML. It is a compiler
for schematic topology, not CAD and not a netlist language.
"""

from .compile import CompileResult, compile_netic
from .parser import ParseError, parse_netic

__all__ = [
    "CompileResult",
    "ParseError",
    "compile_netic",
    "parse_netic",
]
