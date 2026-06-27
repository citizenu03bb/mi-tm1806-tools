# rgbkb/

Bash CLI for the 4-zone keyboard backlight on the TM1806. Uses ACPI WSAA (`\_SB_.MIAP.WSAA`) via `acpi_call` to talk to the EC, plus an EMEM mmap to read the current `KBBR` register (the brightness state needed for the Fn-bypass trick — see the top-level README's "What's novel" section).

See the [top-level README](../README.md) for context, requirements, and the LEBR-bypass mechanism.

## Files

- `rgbkb` — the CLI. Five paint commands (`solid`, `breath`, `wave`, `colorful`, `zone`) plus `brightness` and `status`.
- `tools/`
  - `paint_no_fn.sh` — minimal standalone example of the LEBR=current_KBBR technique (no rgbkb needed). Useful starting point for a re-implementation in another language.
  - `ec_capture_narrated.py` — continuous EMEM sampler at 50 ms with stdin event labels. Useful for observing what the EC does when you press Fn or run a paint command.
  - `emem_paint_test.py` — minimal KBBR-via-EMEM read test.
  - `trace_ec_fn.sh` — bpftrace kprobes on `acpi_ec_*` to confirm whether Fn presses produce host-side EC traffic. (Spoiler: they don't — the painter is fully in-EC; only the post-action SCI is observable from the host.)
  - `non_blanking_lighteffect_test.sh` — earlier discriminating test that demonstrated the LEBR principle.
  - `pure_color_test.sh` — stage-only test (FB00/0101 without a follow-up trigger). Confirms staging without painting.
  - `test_a1_single_lety_sandwich.sh`, `test_a1b_mibox_sandwich.sh` — validate that single-pass and Mi-Box-pattern sandwich with `LETY=N` do NOT refresh from C-registers (so the two-pass for animated modes is canonical, not a workaround).
  - `test_a2_ledz_creg_map.sh` — validates that the static painter reads only `C0Z`, broadcast across whichever LEDZ is targeted.

## Buffer formats (canonical)

```
FB00/0101 stage:    00 FB 01 01 <DT2A=01..08> 02 00 00 <R> <G> <B> 00  + 20×0x00
FB00/0100 trigger:  00 FB 00 01 <LEDZ=04..07> 00 00 00 <LETY> <LSPD> <LEBR=current_KBBR> 00  + 20×0x00
```

Call: `\_SB_.MIAP.WSAA 0x0 {buf}` via `/proc/acpi/call`.

## C-register semantics on TM1806

| C-reg   | Read by                                         |
|---------|-------------------------------------------------|
| `C0Z`   | static painter (LETY=01) — broadcast to all 4 zones via the LEDZ argument; the previous zone's painted color persists |
| `C1Z`   | LETY=04 (COLORFUL) — second wave color           |
| `C2Z..C7Z` | not read by the painter on TM1806 (write-only mirrors) |

So per-zone diversity comes from sequencing — stage `C0Z=color1`, paint LEDZ=04; stage `C0Z=color2`, paint LEDZ=05; etc. Each LEDZ paint snapshots `C0Z` into that zone's persistent state in EC SRAM.

## Recovery

- **Backlight goes dark unexpectedly**: press `Fn + keyboard-brightness` once. The EC re-arms `KBBL`/`KBIT` and re-paints from its internal SRAM. Software recovery via `wsaa_recover.sh`-style writes is **not** reliable; prefer the hardware key.
- **Don't** send `FB00/0100 LETY=0` on a keyboard zone — that puts the EC into a "no-paint" state that requires `systemctl suspend` (or full reboot) to recover. The CLI never does this; if you write your own scripts, skip directly from `LETY=01` to non-zero values.
- **Don't** send `FB00/0400` with `KBIT=0` — past testing showed this puts the EC into a state where Fn no longer re-enables the backlight even across reboot. `0xFF` is the safe value.
