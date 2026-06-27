#!/usr/bin/env python3
"""
Audio visualizer — the keyboard pulses to your music.
=====================================================

Captures system audio output via PipeWire, computes real-time amplitude,
and maps it to the 4-zone keyboard backlight.

Modes: pulse / bands / disco / fire

Usage:
  sudo python3 effects/audiovisualizer.py [mode]
  Ctrl+C to stop — restores green.
"""

import subprocess, struct, math, sys, os, time, signal
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
RGBKB = str(SCRIPT_DIR / ".." / "rgbkb" / "rgbkb")

SAMPLE_RATE = 44100
CHUNK_MS    = 40
CHUNK       = SAMPLE_RATE * CHUNK_MS // 1000
PAINT_MS    = 90         # min ms between keyboard updates (bash CLI ≈ 250 ms)

# ── find the audio monitor source ────────────────────────────────

def get_monitor():
    try:
        real_user = os.environ.get("SUDO_USER", "")
        if not real_user:
            sink = subprocess.check_output(
                ["pactl", "get-default-sink"], text=True, timeout=3
            ).strip()
            return sink + ".monitor" if sink else None
        uid  = os.environ.get("SUDO_UID", "1000")
        runt = f"/run/user/{uid}"
        sink = subprocess.check_output(
            ["sudo", "-u", real_user,
             "env", f"XDG_RUNTIME_DIR={runt}",
             "pactl", "get-default-sink"],
            text=True, timeout=3
        ).strip()
        if sink:
            return sink + ".monitor"
    except Exception as e:
        print(f"Error finding default sink: {e}", file=sys.stderr)
    print("Error: cannot find default audio sink.", file=sys.stderr)
    print("Is pipewire-pulse running?", file=sys.stderr)
    sys.exit(1)

MONITOR = get_monitor()

# ── helpers ──────────────────────────────────────────────────────

def shell(*args):
    subprocess.run(list(args), capture_output=True, timeout=5)

def paint_zone(zone, r, g, b):
    shell("sudo", RGBKB, "zone", zone, f"0x{r:02X}{g:02X}{b:02X}")

def paint_uniform(r, g, b):
    shell("sudo", RGBKB, "solid", f"0x{r:02X}{g:02X}{b:02X}")

def cleanup(sig=None, frame=None):
    paint_uniform(0, 255, 0)
    print("\n  Restored to green.")
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

if os.geteuid() != 0:
    print("Must run as root (sudo).", file=sys.stderr)
    sys.exit(1)

# ── signal processing ─────────────────────────────────────────────

class Goertzel:
    def __init__(self, freq, sample_rate, window=512):
        k = int(0.5 + freq * window / sample_rate)
        self.coeff = 2.0 * math.cos(2.0 * math.pi * k / window)
        self.window = window
        self.buf = [0.0] * window
        self.pos = 0

    def feed(self, sample):
        self.buf[self.pos] = sample
        self.pos = (self.pos + 1) % self.window
        if self.pos != 0:
            return 0.0
        s0, s1 = 0.0, 0.0
        for v in reversed(self.buf):
            s = v + self.coeff * s0 - s1
            s1 = s0; s0 = s
        return (s0*s0 + s1*s1 - self.coeff*s0*s1) ** 0.5 / self.window


class EnvelopeFollower:
    def __init__(self, attack=0.92, release=0.85):
        self.attack  = attack
        self.release = release
        self.value   = 0.0

    def update(self, sample):
        a = self.attack if sample > self.value else self.release
        self.value = a * self.value + (1.0 - a) * sample
        return self.value


def make_bands():
    return [
        Goertzel(50,  SAMPLE_RATE),
        Goertzel(200, SAMPLE_RATE),
        Goertzel(900, SAMPLE_RATE),
        Goertzel(4000,SAMPLE_RATE),
    ]


def open_audio():
    real_user = os.environ.get("SUDO_USER", "")
    uid  = os.environ.get("SUDO_UID", "1000")
    runt = f"/run/user/{uid}"
    cmd = ["pw-cat", "--record", "--target=" + MONITOR,
           "--format=s16", "--rate", str(SAMPLE_RATE), "--channels=1", "-"]
    if real_user:
        cmd = ["sudo", "-u", real_user, "env", f"XDG_RUNTIME_DIR={runt}"] + cmd
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def throttle(last):
    """Return (True, new_last) if enough time has passed, else (False, last)."""
    now = time.monotonic()
    if now - last >= PAINT_MS / 1000.0:
        return True, now
    return False, last


# ── modes ─────────────────────────────────────────────────────────

def mode_pulse():
    print(f"  MODE: pulse — monitor: {MONITOR}")
    smooth = EnvelopeFollower()
    phase  = 0.0
    last   = 0.0
    buf    = bytearray(CHUNK * 2)

    with open_audio() as proc:
        while True:
            n = proc.stdout.readinto(buf)
            if n < CHUNK * 2: break
            samples = struct.unpack(f"<{CHUNK}h", buf)
            total = sum(abs(s) for s in samples) / CHUNK / 32768.0
            total = smooth.update(total)

            ok, last = throttle(last)
            if not ok: continue

            phase  = (phase + total * 0.03) % 1.0
            r,g,b  = hue_to_rgb(phase)
            scale  = 0.12 + total * 3.0
            r = min(255, int(r * scale))
            g = min(255, int(g * scale))
            b = min(255, int(b * scale))
            paint_uniform(r, g, b)


def mode_bands():
    print(f"  MODE: bands — monitor: {MONITOR}")
    bands    = make_bands()
    smooths  = [EnvelopeFollower(0.90, 0.80) for _ in range(4)]
    zone_map = ["bar", "kb-left", "kb-mid", "kb-right"]
    last     = 0.0
    buf      = bytearray(CHUNK * 2)

    with open_audio() as proc:
        while True:
            n = proc.stdout.readinto(buf)
            if n < CHUNK * 2: break
            samples = struct.unpack(f"<{CHUNK}h", buf)

            energies = []
            for i, b in enumerate(bands):
                e = sum(b.feed(s / 32768.0) for s in samples) / CHUNK
                energies.append(smooths[i].update(e))

            ok, last = throttle(last)
            if not ok: continue

            for i, energy in enumerate(energies):
                hue = 0.0 + (1.0 - i / 4.0) * 0.66
                r, g, b = hue_to_rgb(hue)
                scale = max(8, min(255, int(energy * 150000)))
                r = min(255, int(r * scale / 255.0))
                g = min(255, int(g * scale / 255.0))
                b = min(255, int(b * scale / 255.0))
                paint_zone(zone_map[i], r, g, b)


def mode_disco():
    print(f"  MODE: disco — monitor: {MONITOR}")
    bands   = make_bands()
    smooths = [EnvelopeFollower() for _ in range(4)]
    hue     = 0.0
    last    = 0.0
    buf     = bytearray(CHUNK * 2)

    with open_audio() as proc:
        while True:
            n = proc.stdout.readinto(buf)
            if n < CHUNK * 2: break
            samples = struct.unpack(f"<{CHUNK}h", buf)

            energies = []
            for i, b in enumerate(bands):
                e = sum(b.feed(s / 32768.0) for s in samples) / CHUNK
                energies.append(smooths[i].update(e))

            ok, last = throttle(last)
            if not ok: continue

            dominant = energies.index(max(energies))
            hue = (hue + dominant * 0.015) % 1.0
            r, g, b = hue_to_rgb(hue)
            total = sum(energies) / 4.0
            scale = 0.15 + total * 3.5
            r = min(255, int(r * scale))
            g = min(255, int(g * scale))
            b = min(255, int(b * scale))
            paint_uniform(r, g, b)


def mode_fire():
    print(f"  MODE: fire — monitor: {MONITOR}")
    smooth = EnvelopeFollower(0.88, 0.78)
    last   = 0.0
    buf    = bytearray(CHUNK * 2)

    with open_audio() as proc:
        while True:
            n = proc.stdout.readinto(buf)
            if n < CHUNK * 2: break
            samples = struct.unpack(f"<{CHUNK}h", buf)
            total = sum(abs(s) for s in samples) / CHUNK / 32768.0
            total = smooth.update(total)

            ok, last = throttle(last)
            if not ok: continue

            hue = 0.03 + total * 0.10
            r, g, b = hue_to_rgb(hue)
            scale = 0.15 + total * 3.5
            r = min(255, int(r * scale))
            g = min(255, int(g * scale))
            b = min(255, int(b * scale))
            paint_uniform(r, g, b)


def hue_to_rgb(h):
    h *= 6.0; c = 255; x = int(c * (1.0 - abs(h % 2.0 - 1.0)))
    if h < 1:   return (c, x, 0)
    elif h < 2: return (x, c, 0)
    elif h < 3: return (0, c, x)
    elif h < 4: return (0, x, c)
    elif h < 5: return (x, 0, c)
    else:       return (c, 0, x)


if __name__ == "__main__":
    modes = {"pulse": mode_pulse, "bands": mode_bands,
             "disco": mode_disco, "fire": mode_fire}
    mode = sys.argv[1] if len(sys.argv) > 1 else "pulse"
    if mode not in modes:
        print(f"Usage: sudo {sys.argv[0]} {{{('|').join(modes)}}}")
        sys.exit(1)
    try:
        modes[mode]()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        cleanup()
