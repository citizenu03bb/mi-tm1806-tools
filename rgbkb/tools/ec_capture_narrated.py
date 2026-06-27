#!/usr/bin/env python3
"""Continuous EC RAM capture with narrated event labels.

Captures /sys/kernel/debug/ec/ec0/io every 50ms for N seconds while reading
labels from stdin in parallel. Each typed label is timestamped against the
capture timeline. On stop, runs an analysis that ranks EC bytes by how often
their value flipped within each labeled time window vs. outside any window.

Usage:
    sudo python3 ec_capture_narrated.py [seconds]   # default 60

Recommended labels (one per line, then Enter):
    fn        — you just pressed Fn+keyboard-brightness
    magenta   — you just ran rgbkb solid magenta (or any rgbkb command)
    idle      — marking a clean idle window for noise baseline
    anything you want — labels are arbitrary strings

Ctrl-D to stop early. Capture auto-stops at [seconds].
"""
import mmap, os, select, sys, time

# This firmware does NOT use the standard ACPI EC RAM (port 0x62/0x66 / ec_sys
# debugfs gives us bytes that don't contain KBBR/lighting state). Instead the
# DSDT declares KBBR/KBIT/EVBF etc. inside an EMEM SystemMemory region at
# physical address 0xFE708000, length 0xBFF (3071 bytes). We mmap /dev/mem
# (CONFIG_STRICT_DEVMEM allows this since the region is in /proc/iomem as
# 'pnp 00:01' I/O memory) to read it directly and continuously.
EMEM_PHYS = 0xFE708000
EMEM_SIZE = 0x0C00       # round up to page (3 pages = 12KB; only first 3071 bytes meaningful)
INTERVAL_S = 0.05
WINDOW_BEFORE_S = 0.3
WINDOW_AFTER_S = 1.0
# Known DSDT field offsets for orientation in printouts:
KNOWN_FIELDS = {
    0x300: "F1SP[0]", 0x301: "F1SP[1]", 0x302: "F2SP[0]", 0x303: "F2SP[1]",
    0x305: "TMSW", 0x308: "VIUF_byte", 0x30C: "PRLL", 0x30D: "KBBR",
    0x30E: "KBIT[0]", 0x30F: "KBIT[1]",
    0x344: "ACDF/PSUS/WONL", 0x346: "MCUR[0]", 0x347: "MCUR[1]",
    0x352: "ARPL/BTON/ECLS", 0x358: "CPUT", 0x359: "GPUS/KBBL",
    0x35E: "WINK/FNKY/TPON/PWLE/FANM",
}


def capture(duration: float):
    captures: list[tuple[float, bytes]] = []
    events: list[tuple[float, str]] = []

    fd = os.open("/dev/mem", os.O_RDONLY)
    mm = mmap.mmap(fd, EMEM_SIZE, mmap.MAP_SHARED, mmap.PROT_READ, offset=EMEM_PHYS)

    t0 = time.monotonic()
    next_cap = t0
    end = t0 + duration

    while time.monotonic() < end:
        now = time.monotonic()
        if now >= next_cap:
            data = bytes(mm[:EMEM_SIZE])
            captures.append((now - t0, data))
            next_cap += INTERVAL_S
            # If we fell behind, jump forward (avoid catch-up burst)
            if next_cap < now:
                next_cap = now + INTERVAL_S
        # Wait for stdin or until next capture
        timeout = max(0.0, next_cap - time.monotonic())
        r, _, _ = select.select([sys.stdin], [], [], min(0.02, timeout))
        if r:
            line = sys.stdin.readline()
            if not line:
                break
            label = line.strip()
            if label:
                t = time.monotonic() - t0
                events.append((t, label))
                print(f"  [{t:6.2f}s] event: {label}", flush=True)

    mm.close()
    os.close(fd)
    return captures, events


def label_for(off: int) -> str:
    return KNOWN_FIELDS.get(off, "")


def analyze(captures, events):
    if not captures:
        print("no captures")
        return
    n_bytes = min(len(c[1]) for c in captures)
    print(f"\n[captured {len(captures)} frames over {captures[-1][0]:.1f}s, {n_bytes} EMEM bytes]")
    print(f"[{len(events)} labeled events]")

    if not events:
        # Fallback: just report which bytes changed at all
        flips = [0] * n_bytes
        for k in range(1, len(captures)):
            for i in range(n_bytes):
                if captures[k][1][i] != captures[k - 1][1][i]:
                    flips[i] += 1
        active = sorted([(f, i) for i, f in enumerate(flips) if f > 0], reverse=True)
        print("\n=== bytes that flipped during capture (no labels to correlate) ===")
        print(f"  {'off':<5} {'flips':>6}")
        for f, i in active[:30]:
            print(f"  0x{i:02x}  {f:>6}")
        return

    # Group windows by label
    windows_by_label: dict[str, list[tuple[float, float]]] = {}
    for t, label in events:
        windows_by_label.setdefault(label, []).append((t - WINDOW_BEFORE_S, t + WINDOW_AFTER_S))

    def in_any_window(t, windows):
        return any(a <= t <= b for a, b in windows)

    # Total time covered by any window (for normalization)
    all_windows = [w for ws in windows_by_label.values() for w in ws]
    total_time = captures[-1][0]
    in_event_time = sum(min(b, total_time) - max(a, 0) for a, b in all_windows if b > 0)
    idle_time = max(0.001, total_time - in_event_time)

    # Per-byte, per-label flip counts
    labels = sorted(windows_by_label.keys())
    label_flips = {l: [0] * n_bytes for l in labels}
    idle_flips = [0] * n_bytes
    label_seconds = {l: sum(b - a for a, b in ws) for l, ws in windows_by_label.items()}

    for k in range(1, len(captures)):
        t = captures[k][0]
        prev, curr = captures[k - 1][1], captures[k][1]
        # Determine label bucket for this transition
        bucket = None
        for l in labels:
            if in_any_window(t, windows_by_label[l]):
                bucket = l
                break
        for i in range(n_bytes):
            if prev[i] != curr[i]:
                if bucket:
                    label_flips[bucket][i] += 1
                else:
                    idle_flips[i] += 1

    print(f"\n=== Per-byte change-rate (flips/sec) by label ===")
    print(f"  Window: {WINDOW_BEFORE_S}s before to {WINDOW_AFTER_S}s after each label")
    print(f"  Idle time outside any label window: {idle_time:.1f}s")
    for l in labels:
        print(f"  Label '{l}': {len(windows_by_label[l])} occurrence(s), total {label_seconds[l]:.1f}s window")
    print()

    # Rank by max(rate_in_label) - rate_idle
    rows = []
    for i in range(n_bytes):
        idle_rate = idle_flips[i] / idle_time
        label_rates = {l: label_flips[l][i] / max(0.001, label_seconds[l]) for l in labels}
        max_signal = max((r - idle_rate, l) for l, r in label_rates.items()) if labels else (0, "")
        rows.append((max_signal[0], i, idle_rate, label_rates, max_signal[1]))
    rows.sort(reverse=True)

    header = f"  {'off':<5} {'idle/s':>8}  " + "  ".join(f"{l + '/s':>8}" for l in labels) + "  best-signal"
    print(header)
    for signal, i, idle_rate, label_rates, best_label in rows[:30]:
        if idle_rate < 0.05 and all(r < 0.05 for r in label_rates.values()):
            continue  # totally quiet byte — skip
        line = f"  0x{i:02x}  {idle_rate:>7.2f}  " + "  ".join(
            f"{label_rates[l]:>7.2f}" for l in labels
        )
        tag = ""
        if signal > 0.5:
            tag = f"  ** {best_label} (+{signal:.1f}/s)"
        elif signal > 0.1:
            tag = f"  {best_label} (+{signal:.1f}/s)"
        known = label_for(i)
        if known:
            tag = f"  [{known}]" + tag
        line += tag
        print(line)


def main():
    if os.geteuid() != 0:
        print("run as root: sudo python3 ec_capture_narrated.py [seconds]", file=sys.stderr)
        sys.exit(1)
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0

    base = os.environ.get("EC_SNAPSHOTS_DIR") \
        or os.path.join(os.path.dirname(os.path.realpath(__file__)), "ec_snapshots")
    out_dir = os.path.join(base, f"emem_{time.strftime('%Y%m%d-%H%M%S')}")
    os.makedirs(out_dir, exist_ok=True)

    print(f"[ec_capture_narrated  reading EMEM @ 0x{EMEM_PHYS:x} ({EMEM_SIZE}B)  "
          f"duration={duration}s  interval={INTERVAL_S * 1000:.0f}ms  out={out_dir}]")
    print(f"[type labels then Enter — e.g.  fn  magenta  green  idle]")
    print(f"[Ctrl-D to stop early; auto-stops at duration]")
    print()

    try:
        captures, events = capture(duration)
    except KeyboardInterrupt:
        captures, events = [], []
        print("\n[interrupted]")

    # Persist raw data
    with open(f"{out_dir}/captures.bin", "wb") as f:
        for t, data in captures:
            f.write(int(t * 1e6).to_bytes(8, "little"))
            f.write(data)
    with open(f"{out_dir}/events.txt", "w") as f:
        for t, label in events:
            f.write(f"{t:.4f}\t{label}\n")

    analyze(captures, events)
    print(f"\n[raw saved to {out_dir}/]")


if __name__ == "__main__":
    main()
