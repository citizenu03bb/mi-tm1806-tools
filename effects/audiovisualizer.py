#!/usr/bin/env python3
"""
Audio visualizer — the keyboard pulses to your music.
=====================================================

Captures system audio via PulseAudio, computes real-time amplitude,
and maps it to the 4-zone keyboard backlight.  No numpy/sounddevice
required — uses parec subprocess + pure-Python DSP.

Modes:
  pulse   — all zones share one colour; brightness follows volume
  bands   — 4 frequency bands → 4 zones (bass→bar, mids→left/mid, treble→right)
  disco   — colour shifts with frequency content
  fire    — warm glow that intensifies with volume

Usage:
  sudo python3 effects/audiovisualizer.py [mode] [--speed N]

  Ctrl+C to stop — restores green.
"""

import subprocess, struct, math, sys, os, time, signal
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
RGBKB = str(SCRIPT_DIR / ".." / "rgbkb" / "rgbkb")

SAMPLE_RATE   = 44100
CHUNK_MS      = 40
CHUNK         = SAMPLE_RATE * CHUNK_MS // 1000
FORMAT        = "s16le"       # 16-bit signed little-endian
CHANNELS      = 1
BYTES_PER     = 2
RESTORE_COLOR = "green"
LOW_CUT       = 20.0          # Hz — subsonic filter

# ── helpers ────────────────────────────────────────────────────────

def shell(*args):
    return subprocess.run(list(args), capture_output=True, timeout=5)

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

# ── signal processing ───────────────────────────────────────────────

class RingBuffer:
    """Fixed-size FIFO for delay lines."""
    def __init__(self, size):
        self.buf = [0.0] * size
        self.pos = 0
        self.size = size

    def push(self, val):
        self.buf[self.pos] = val
        self.pos = (self.pos + 1) % self.size

    def __getitem__(self, idx):
        return self.buf[(self.pos - 1 - idx) % self.size]


class Goertzel:
    """Single-bin DFT — efficient for a small number of frequency bands."""
    def __init__(self, freq, sample_rate):
        k = int(0.5 + freq * 64 / sample_rate)  # 64-sample window
        self.coeff = 2.0 * math.cos(2.0 * math.pi * k / 64)
        self.window = 64
        self.buf = RingBuffer(self.window)

    def feed(self, sample):
        self.buf.push(sample)
        if self.pos() < self.window:
            return 0.0
        s0, s1 = 0.0, 0.0
        for i in range(self.window):
            s = self.buf[self.window - 1 - i] + self.coeff * s0 - s1
            s1 = s0
            s0 = s
        return (s0 * s0 + s1 * s1 - self.coeff * s0 * s1) ** 0.5 / self.window

    def pos(self):
        return self.buf.pos


class EnvelopeFollower:
    """Smooth envelope with attack / release."""
    def __init__(self, attack=0.92, release=0.85):
        self.attack  = attack
        self.release = release
        self.value   = 0.0

    def update(self, sample):
        a = self.attack if sample > self.value else self.release
        self.value = a * self.value + (1.0 - a) * sample
        return self.value


# ── frequency bands ─────────────────────────────────────────────────

def make_bands():
    """4 frequency bands: sub-bass, bass, mids, highs."""
    return [
        Goertzel(50,  SAMPLE_RATE),   # sub-bass
        Goertzel(200, SAMPLE_RATE),   # bass
        Goertzel(900, SAMPLE_RATE),   # mids
        Goertzel(4000,SAMPLE_RATE),   # highs
    ]


# ── visualizer modes ────────────────────────────────────────────────

def mode_pulse(speed=1.0):
    """All zones share one colour; brightness follows overall volume."""
    print("  MODE: pulse — amplitude-driven brightness")
    phase = 0.0
    smooth = EnvelopeFollower()
    bands  = make_bands()
    buf    = bytearray(CHUNK * BYTES_PER)

    with subprocess.Popen(
        ["pw-cat", "--record", "--format=s16", "--rate", str(SAMPLE_RATE),
         "--channels=1", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    ) as proc:
        while True:
            n = proc.stdout.readinto(buf)
            if n < CHUNK * BYTES_PER:
                break
            samples = struct.unpack(f"<{CHUNK}h", buf)
            total = sum(abs(s) for s in samples) / CHUNK / 32768.0
            total = smooth.update(total)

            # Map 0..1 to hue (phase rotates slowly)
            phase = (phase + speed * total * 0.02) % 1.0
            r, g, b = hue_to_rgb(phase)

            # Scale by volume
            scale = 0.15 + total * 2.5
            r = min(255, int(r * scale))
            g = min(255, int(g * scale))
            b = min(255, int(b * scale))

            paint_uniform(r, g, b)


def mode_bands(speed=1.0):
    """4 frequency bands → 4 zones."""
    print("  MODE: bands — bass→bar, low-mid→left, high-mid→mid, treble→right")
    bands    = make_bands()
    smooths  = [EnvelopeFollower(0.90, 0.80) for _ in range(4)]
    zone_map = ["bar", "kb-left", "kb-mid", "kb-right"]
    buf      = bytearray(CHUNK * BYTES_PER)

    with subprocess.Popen(
        ["pw-cat", "--record", "--format=s16", "--rate", str(SAMPLE_RATE),
         "--channels=1", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    ) as proc:
        while True:
            n = proc.stdout.readinto(buf)
            if n < CHUNK * BYTES_PER:
                break
            samples = struct.unpack(f"<{CHUNK}h", buf)

            # Feed each band
            for i, b in enumerate(bands):
                energy = sum(b.feed(s / 32768.0) for s in samples) / CHUNK
                energy = smooths[i].update(energy)
                # Map to colour — redder for bass, bluer for treble
                hue = 0.0 + (1.0 - i / 4.0) * 0.66  # red → blue
                r, g, b = hue_to_rgb(hue)
                scale = min(255, int(energy * 600))
                r = min(255, int(r * scale / 255.0))
                g = min(255, int(g * scale / 255.0))
                b = min(255, int(b * scale / 255.0))
                paint_zone(zone_map[i], r, g, b)


def mode_disco(speed=1.0):
    """Colour shifts with frequency content — total party."""
    print("  MODE: disco — colour shifts with the beat")
    bands   = make_bands()
    smooths = [EnvelopeFollower() for _ in range(4)]
    hue     = 0.0
    buf     = bytearray(CHUNK * BYTES_PER)

    with subprocess.Popen(
        ["pw-cat", "--record", "--format=s16", "--rate", str(SAMPLE_RATE),
         "--channels=1", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    ) as proc:
        while True:
            n = proc.stdout.readinto(buf)
            if n < CHUNK * BYTES_PER:
                break
            samples = struct.unpack(f"<{CHUNK}h", buf)

            energies = []
            for i, b in enumerate(bands):
                energy = sum(b.feed(s / 32768.0) for s in samples) / CHUNK
                energies.append(smooths[i].update(energy))

            # Dominant frequency shifts the hue
            dominant = energies.index(max(energies))
            hue = (hue + dominant * 0.01) % 1.0

            r, g, b = hue_to_rgb(hue)
            total = sum(energies) / 4.0
            scale = 0.2 + total * 3.0
            r = min(255, int(r * scale))
            g = min(255, int(g * scale))
            b = min(255, int(b * scale))
            paint_uniform(r, g, b)


def mode_fire(speed=1.0):
    """Warm fire-like glow that intensifies with volume."""
    print("  MODE: fire — warm amber glow intensifies with volume")
    smooth = EnvelopeFollower(0.88, 0.78)
    buf    = bytearray(CHUNK * BYTES_PER)

    with subprocess.Popen(
        ["pw-cat", "--record", "--format=s16", "--rate", str(SAMPLE_RATE),
         "--channels=1", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    ) as proc:
        while True:
            n = proc.stdout.readinto(buf)
            if n < CHUNK * BYTES_PER:
                break
            samples = struct.unpack(f"<{CHUNK}h", buf)
            total = sum(abs(s) for s in samples) / CHUNK / 32768.0
            total = smooth.update(total)

            # Fire: stays in red/orange/yellow range
            hue = 0.03 + total * 0.08   # around 0.03-0.11 (red-orange)
            r, g, b = hue_to_rgb(hue)
            scale = 0.2 + total * 3.0
            r = min(255, int(r * scale))
            g = min(255, int(g * scale))
            b = min(255, int(b * scale))
            paint_uniform(r, g, b)


# ── utility ─────────────────────────────────────────────────────────

def hue_to_rgb(h):
    """HSV hue 0..1 → RGB (0..255, 0..255, 0..255).  S=V=1."""
    h *= 6.0
    c = 255
    x = int(c * (1.0 - abs(h % 2.0 - 1.0)))
    if h < 1:
        return (c, x, 0)
    elif h < 2:
        return (x, c, 0)
    elif h < 3:
        return (0, c, x)
    elif h < 4:
        return (0, x, c)
    elif h < 5:
        return (x, 0, c)
    else:
        return (c, 0, x)


# ── main ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    modes = {
        "pulse": mode_pulse,
        "bands": mode_bands,
        "disco": mode_disco,
        "fire":  mode_fire,
    }

    mode = sys.argv[1] if len(sys.argv) > 1 else "pulse"
    if mode not in modes:
        print(f"Usage: sudo {sys.argv[0]} {{{('|').join(modes)}}}")
        print(f"  pulse  — amplitude-driven brightness, colour rotates")
        print(f"  bands  — 4 frequency bands → 4 zones (bass→bar, ...)")
        print(f"  disco  — colour shifts with the beat")
        print(f"  fire   — warm glow that intensifies with volume")
        sys.exit(1)

    try:
        modes[mode]()
    except EOFError:
        cleanup()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        cleanup()
