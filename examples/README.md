# Netic examples

These `*.netic` files test the language (relative integer-grid topology). They
are analog teaching circuits — filters, CE/CS amplifiers, a long-tailed pair —
**not** fab PCB examples. No LCSC numbers or footprints. Discrete parts only
(R, L, C, D, BJT, MOSFET). Integrated circuits are out of scope until the
syntax can describe them.

Compile from the repo root:

```bash
python -m netic examples/04_common_emitter.netic -o out/ce
```
