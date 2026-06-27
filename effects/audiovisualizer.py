#!/usr/bin/env python3
"""
Audio visualizer — the keyboard pulses to your music.
=====================================================

Captures system audio output via PipeWire, computes real-time
amplitude with a Goertzel filter bank, and maps it to the 4-zone
keyboard backlight.  Uses pactl to find the default sink — survives
reboots, headphone switches, etc.

Modes:
  pulse   — all zones share one colour; brightness follows volume
  bands   — 4 frequency bands → 4 zones (bass→bar, …)
  disco   — colour shifts with frequency content
  fire    — warm glow that intensifies with volume

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

# ── find the audio monitor source ────────────────────────────────

def get_monitor():
    """Return the PulseAudio monitor source name.

    Uses pactl via sudo -u on the original user's PulseAudio session,
    since the PA socket is per-user and sudo changes the effective uid.
    """
    try:
        real_user = os.environ.get("SUDO_USER", "")
        if not real_user:
            # Not under sudo — just try pactl directly
            sink = subprocess.check_output(
                ["pactl", "get-default-sink"], text=True, timeout=3
            ).strip()
            return sink + ".monitor" if sink else None

        # Under sudo: need to pass the original user's XDG_RUNTIME_DIR
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

class RingBuffer:
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
    """Single-bin DFT — efficient for a few frequency bands."""
    def __init__(self, freq, sample_rate):
        k = int(0.5 + freq * 64 / sample_rate)
        self.coeff = 2.0 * math.cos(2.0 * math.pi * k / 64)
        self.window = 64
        self.buf = RingBuffer(self.window)

    def feed(self, sample):
        self.buf.push(sample)
        if self.buf.pos < self.window:
            return 0.0
        s0, s1 = 0.0, 0.0
        for i in range(self.window):
            s = self.buf[self.window - 1 - i] + self.coeff * s0 - s1
            s1 = s0
            s0 = s
        return (s0 * s0 + s1 * s1 - self.coeff * s0 * s1) ** 0.5 / self.window


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
        Goertzel(50,  SAMPLE_RATE),   # sub-bass
        Goertzel(200, SAMPLE_RATE),   # bass
        Goertzel(900, SAMPLE_RATE),   # mids
        Goertzel(4000,SAMPLE_RATE),   # highs
    ]


# ── PipeWire capture ──────────────────────────────────────────────

def open_audio():
    """Open a PipeWire capture stream from the monitor source,
    running pw-cat as the original user (PipeWire is per-user)."""
    real_user = os.environ.get("SUDO_USER", "")
    uid  = os.environ.get("SUDO_UID", "1000")
    runt = f"/run/user/{uid}"

    cmd = ["pw-cat", "--record", "--target=" + MONITOR,
           "--format=s16", "--rate", str(SAMPLE_RATE), "--channels=1", "-"]

    if real_user:
        cmd = ["sudo", "-u", real_user,
               "env", f"XDG_RUNTIME_DIR={runt}"] + cmd

    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


# ── modes ─────────────────────────────────────────────────────────

def mode_pulse():
    print(f"  MODE: pulse — monitor: {MONITOR}")
    smooth = EnvelopeFollower()
    phase  = 0.0
    buf    = bytearray(CHUNK * 2)

    with open_audio() as proc:
        while True:
            n = proc.stdout.readinto(buf)
            if n < CHUNK * 2:
                break
            samples = struct.unpack(f"<{CHUNK}h", buf)
            total = sum(abs(s) for s in samples) / CHUNK / 32768.0
            total = smooth.update(total)

            phase = (phase + total * 0.02) % 1.0
            r, g, b = hue_to_rgb(phase)
            scale = 0.15 + total * 2.5
            r = min(255, int(r * scale))
            g = min(255, int(g * scale))
            b = min(255, int(b * scale))
            paint_uniform(r, g, b)


def mode_bands():
    print(f"  MODE: bands — bass→bar / treble→right  (monitor: {MONITOR})")
    bands    = make_bands()
    smooths  = [EnvelopeFollower(0.90, 0.80) for _ in range(4)]
    zone_map = ["bar", "kb-left", "kb-mid", "kb-right"]
    buf      = bytearray(CHUNK * 2)

    with open_audio() as proc:
        while True:
            n = proc.stdout.readinto(buf)
            if n < CHUNK * 2:
                break
            samples = struct.unpack(f"<{CHUNK}h", buf)
            for i, b in enumerate(bands):
                energy = sum(b.feed(s / 32768.0) for s in samples) / CHUNK
                energy = smooths[i].update(energy)
                hue = 0.0 + (1.0 - i / 4.0) * 0.66
                r, g, b = hue_to_rgb(hue)
                scale = min(255, int(energy * 600))
                r = min(255, int(r * scale / 255.0))
                g = min(255, int(g * scale / 255.0))
                b = min(255, int(b * scale / 255.0))
                paint_zone(zone_map[i], r, g, b)


def mode_disco():
    print(f"  MODE: disco — colour shifts with the beat  (monitor: {MONITOR})")
    bands   = make_bands()
    smooths = [EnvelopeFollower() for _ in range(4)]
    hue     = 0.0
    buf     = bytearray(CHUNK * 2)

    with open_audio() as proc:
        while True:
            n = proc.stdout.readinto(buf)
            if n < CHUNK * 2:
                break
            samples = struct.unpack(f"<{CHUNK}h", buf)
            energies = []
            for i, b in enumerate(bands):
                energy = sum(b.feed(s / 32768.0) for s in samples) / CHUNK
                energies.append(smooths[i].update(energy))
            dominant = energies.index(max(energies))
            hue = (hue + dominant * 0.01) % 1.0
            r, g, b = hue_to_rgb(hue)
            total = sum(energies) / 4.0
            scale = 0.2 + total * 3.0
            r = min(255, int(r * scale))
            g = min(255, int(g * scale))
            b = min(255, int(b * scale))
            paint_uniform(r, g, b)


def mode_fire():
    print(f"  MODE: fire — warm glow intensifies with volume  (monitor: {MONITOR})")
    smooth = EnvelopeFollower(0.88, 0.78)
    buf    = bytearray(CHUNK * 2)

    with open_audio() as proc:
        while True:
            n = proc.stdout.readinto(buf)
            if n < CHUNK * 2:
                break
            samples = struct.unpack(f"<{CHUNK}h", buf)
            total = sum(abs(s) for s in samples) / CHUNK / 32768.0
            total = smooth.update(total)
            hue = 0.03 + total * 0.08
            r, g, b = hue_to_rgb(hue)
            scale = 0.2 + total * 3.0
            r = min(255, int(r * scale))
            g = min(255, int(g * scale))
            b = min(255, int(b * scale))
            paint_uniform(r, g, b)


# ── utility ───────────────────────────────────────────────────────

def hue_to_rgb(h):
    h *= 6.0
    c = 255
    x = int(c * (1.0 - abs(h % 2.0 - 1.0)))
    if h < 1:   return (c, x, 0)
    elif h < 2: return (x, c, 0)
    elif h < 3: return (0, c, x)
    elif h < 4: return (0, x, c)
    elif h < 5: return (x, 0, c)
    else:       return (c, 0, x)


# ── main ──────────────────────────────────────────────────────────

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
        print(f"  pulse — amplitude-driven brightness, colour rotates")
        print(f"  bands — 4 frequency bands → 4 zones (bass→bar, …)")
        print(f"  disco — colour shifts with the beat")
        print(f"  fire  — warm amber intensifies with volume")
        sys.exit(1)
    try:
        modes[mode]()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        cleanup()
