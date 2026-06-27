#!/usr/bin/env python3
"""mi-hotkey daemon.

Multi-user system service: listens for ACPI WMI events from the Mi Gaming
Laptop (TIMI TM1806) macro-key strip and dispatches per-user actions to
whoever is currently logged in at the seat0 console.

Config resolution per event:
  1.  ~<active-user>/.config/mi-hotkey/config.toml   (preferred)
  2.  $MI_HOTKEY_CONFIG  or  /etc/mi-hotkey/config.toml   (system fallback)

If MI_HOTKEY_USER is set, the daemon ignores active-session detection and
dispatches as that user (useful for headless testing).

Run as root.
"""

from __future__ import annotations

import glob
import os
import pwd
import signal
import subprocess
import sys
import time
import tomllib

# ── constants ─────────────────────────────────────────────────────────────────

SYSTEM_CONFIG_DEFAULT = "/etc/mi-hotkey/config.toml"
SYSTEM_CONFIG_PATH = os.environ.get("MI_HOTKEY_CONFIG", SYSTEM_CONFIG_DEFAULT)
FORCED_USER = os.environ.get("MI_HOTKEY_USER")  # None = auto-detect active

GUID_MIAP_EVENT = "B74AF83F"   # macro keys
GUID_FAN_MODE_A = "EB2464D2"   # fan: WMID notify 0xA2 (boost)
GUID_FAN_MODE_B = "B35609C4"   # fan: WMID notify 0xA9 (normal)

# Kernel ≥6.10 acpi_listen reports unbound WMI events as "wmi PNP0C14:NN ..."
# instead of "<GUID> ..." — only the parent ACPI device-name and notify code
# survive. We need to map the parent ACPI device-name → handler kind. The
# instance numbers come from ACPI enumeration order, which can shift if BIOS
# updates reorder devices. Build the map dynamically by walking sysfs.
GUID_TO_HANDLER = {
    GUID_MIAP_EVENT: "miap_event",
    GUID_FAN_MODE_A: "fan_event",
    GUID_FAN_MODE_B: "fan_event",
}


def discover_pnp_handlers() -> dict[str, str]:
    """Walk /sys/bus/wmi/devices/ and return {PNP0C14:NN: handler_kind}.

    For each known event-firing GUID, find which PNP0C14 instance hosts it
    (via the realpath of the sysfs entry) and register that PNP-name as the
    dispatch key. Multiple GUIDs may map to the same PNP instance (e.g. both
    fan GUIDs share PNP0C14:00) — last write wins, but all GUIDs in a single
    handler kind agree on the kind, so the result is deterministic.
    """
    mapping: dict[str, str] = {}
    for guid_dir in glob.glob("/sys/bus/wmi/devices/*"):
        guid_full = os.path.basename(guid_dir).upper()
        # Match by GUID prefix (first 8 hex chars uniquely identify the GUID).
        prefix = guid_full[:8]
        kind = next(
            (h for g, h in GUID_TO_HANDLER.items() if prefix == g.upper()),
            None,
        )
        if kind is None:
            continue
        # Resolve realpath to find the parent PNP0C14:NN platform device.
        # Path looks like /sys/devices/platform/PNP0C14:04/wmi_bus/wmi_bus-PNP0C14:04/<GUID>
        real = os.path.realpath(guid_dir)
        pnp = next(
            (p for p in real.split(os.sep) if p.startswith("PNP0C14:")),
            None,
        )
        if pnp is None:
            log(f"  ! could not find PNP0C14 parent for {guid_full}")
            continue
        mapping[pnp] = kind
    return mapping


# Populated at startup by main(); empty here so module-level imports stay safe.
PNP_TO_HANDLER: dict[str, str] = {}

ACPI_CALL_PATH = "/proc/acpi/call"
WED_OBJECT = r"\_SB.MIAP._WED"

# Per the DSDT (~/rgb-test/DSDT.dsl, _Q61–_Q75): EVT1 byte 2 in EVBF.
EVT1_MAP = {
    0x01: ("m1", "press"),   0x06: ("m1", "release"),
    0x02: ("m2", "press"),   0x07: ("m2", "release"),
    0x03: ("m3", "press"),   0x08: ("m3", "release"),
    0x04: ("m4", "press"),   0x09: ("m4", "release"),
    0x05: ("m5", "press"),   0x0A: ("m5", "release"),
}

# ── logging ───────────────────────────────────────────────────────────────────


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ── user session env detection ────────────────────────────────────────────────


_SESSION_KEYS = (
    "DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS",
    "XDG_RUNTIME_DIR", "XAUTHORITY", "XDG_SESSION_TYPE",
)


def find_user_session_env(username: str) -> dict[str, str]:
    """Scan the user's processes and return the environ richest in session
    variables. systemd --user alone is insufficient because at boot time it
    starts before the X session imports DISPLAY/XAUTHORITY. gnome-shell
    (or any compositor / graphical-session leaf process) carries the full set."""
    try:
        uid = pwd.getpwnam(username).pw_uid
    except KeyError:
        log(f"user {username!r} not found")
        return {}
    best_env: dict[str, str] = {}
    best_score = -1
    for pid_str in os.listdir("/proc"):
        if not pid_str.isdigit():
            continue
        pid_path = f"/proc/{pid_str}"
        try:
            if os.stat(pid_path).st_uid != uid:
                continue
            with open(f"{pid_path}/environ", "rb") as f:
                blob = f.read()
        except (FileNotFoundError, PermissionError):
            continue
        env: dict[str, str] = {}
        for kv in blob.split(b"\x00"):
            if not kv or b"=" not in kv:
                continue
            k, v = kv.split(b"=", 1)
            try:
                env[k.decode()] = v.decode()
            except UnicodeDecodeError:
                continue
        score = sum(1 for k in _SESSION_KEYS if k in env)
        if score > best_score:
            best_score = score
            best_env = env
            if score >= len(_SESSION_KEYS) - 1:
                return env  # rich enough — stop scanning
    return best_env


# ── ACPI _WED via acpi_call ───────────────────────────────────────────────────


def call_wed(notify: int = 0x80) -> bytes:
    with open(ACPI_CALL_PATH, "w") as f:
        f.write(f"{WED_OBJECT} 0x{notify:X}")
    with open(ACPI_CALL_PATH, "r") as f:
        raw = f.read().rstrip("\x00\n ")
    if not raw.startswith("{"):
        raise RuntimeError(f"unexpected _WED response: {raw!r}")
    parts = [p.strip() for p in raw.strip("{} \t\n").split(",") if p.strip()]
    return bytes(int(p, 16) for p in parts)


# ── uinput (lazy import; optional) ────────────────────────────────────────────


_uinput = None
_uinput_warn_shown = False


def get_uinput():
    """Return the global UInput device, creating it on first use. Returns None
    if python3-evdev isn't installed (logs a warning once)."""
    global _uinput, _uinput_warn_shown
    if _uinput is not None:
        return _uinput
    try:
        import evdev  # type: ignore
        from evdev import ecodes, UInput  # noqa
    except ImportError:
        if not _uinput_warn_shown:
            log("python3-evdev not installed: 'key' actions are disabled. "
                "`sudo apt install python3-evdev` to enable.")
            _uinput_warn_shown = True
        return None

    keys = [
        # Programmable
        "KEY_PROG1", "KEY_PROG2", "KEY_PROG3", "KEY_PROG4",
        # Extended F-row
        *[f"KEY_F{i}" for i in range(1, 25)],
        # Media transport
        "KEY_PLAYPAUSE", "KEY_PLAY", "KEY_PAUSE", "KEY_STOP",
        "KEY_NEXTSONG", "KEY_PREVIOUSSONG",
        # Audio
        "KEY_VOLUMEUP", "KEY_VOLUMEDOWN", "KEY_MUTE", "KEY_MICMUTE",
        # Brightness / kbd
        "KEY_BRIGHTNESSUP", "KEY_BRIGHTNESSDOWN",
        "KEY_KBDILLUMTOGGLE", "KEY_KBDILLUMUP", "KEY_KBDILLUMDOWN",
        # System
        "KEY_SLEEP", "KEY_POWER", "KEY_WAKEUP", "KEY_SCREENLOCK",
        # App launchers
        "KEY_CALC", "KEY_HOMEPAGE", "KEY_MAIL", "KEY_FILE", "KEY_WWW",
        "KEY_SEARCH", "KEY_BOOKMARKS",
        # Modifiers + alpha-num + arrows + common (lets users build chord-likes)
        "KEY_LEFTSHIFT", "KEY_RIGHTSHIFT", "KEY_LEFTCTRL", "KEY_RIGHTCTRL",
        "KEY_LEFTALT", "KEY_RIGHTALT", "KEY_LEFTMETA", "KEY_RIGHTMETA",
        "KEY_ENTER", "KEY_SPACE", "KEY_TAB", "KEY_BACKSPACE", "KEY_ESC",
        "KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT",
        "KEY_HOME", "KEY_END", "KEY_PAGEUP", "KEY_PAGEDOWN",
        *[f"KEY_{c.upper()}" for c in "abcdefghijklmnopqrstuvwxyz"],
        *[f"KEY_{c}" for c in "0123456789"],
    ]
    codes = []
    for name in keys:
        c = getattr(ecodes, name, None)
        if c is not None:
            codes.append(c)
    try:
        _uinput = UInput({ecodes.EV_KEY: codes}, name="mi-hotkey")
        log(f"uinput device created (mi-hotkey, {len(codes)} keys)")
    except Exception as e:
        log(f"uinput create failed: {e}")
        return None
    return _uinput


def inject_key(code_name: str, edge: str = "tap") -> None:
    """edge: 'tap' (down+up), 'down', or 'up'."""
    ui = get_uinput()
    if ui is None:
        return
    from evdev import ecodes  # type: ignore
    code = getattr(ecodes, code_name, None)
    if code is None:
        log(f"  ! unknown key code {code_name!r}")
        return
    if edge in ("tap", "down"):
        ui.write(ecodes.EV_KEY, code, 1)
    if edge in ("tap", "up"):
        ui.write(ecodes.EV_KEY, code, 0)
    ui.syn()


# ── per-user context ──────────────────────────────────────────────────────────


class UserContext:
    """One active user's resolved state: identity, session env, config."""

    def __init__(self, username: str):
        pw = pwd.getpwnam(username)            # raises KeyError if unknown
        self.username = username
        self.uid = pw.pw_uid
        self.gid = pw.pw_gid
        self.home = pw.pw_dir
        self._env: dict[str, str] | None = None
        self._config: dict | None = None
        self._config_mtime: float | None = None
        self._config_path: str | None = None

    @property
    def env(self) -> dict[str, str]:
        if self._env is None:
            self._env = find_user_session_env(self.username)
            if not self._env:
                log(f"  WARN: no session env for {self.username!r}; "
                    "shell/notify actions may fail")
        return self._env

    def invalidate_env(self) -> None:
        self._env = None

    def resolve_config_path(self) -> str:
        per_user = os.path.join(self.home, ".config/mi-hotkey/config.toml")
        if os.path.exists(per_user):
            return per_user
        return SYSTEM_CONFIG_PATH

    def load_config(self) -> dict:
        """Re-read config if its mtime has changed (or first call). Cheap
        enough to do per event — avoids needing inotify or SIGHUP for edits."""
        path = self.resolve_config_path()
        try:
            mtime = os.path.getmtime(path)
        except FileNotFoundError:
            if self._config_path != path or self._config is None:
                log(f"  no config for {self.username!r} (tried {path}) — empty")
            self._config = {}
            self._config_path = path
            self._config_mtime = None
            return self._config

        if (path == self._config_path
                and self._config_mtime == mtime
                and self._config is not None):
            return self._config

        try:
            with open(path, "rb") as f:
                self._config = tomllib.load(f)
            self._config_path = path
            self._config_mtime = mtime
            log(f"  loaded config for {self.username!r}: {path} "
                f"({len(self._config)} sections)")
        except Exception as e:
            log(f"  ! config load error for {self.username!r} ({path}): {e}")
            self._config = {}
        return self._config


# ── active user detection ─────────────────────────────────────────────────────


def get_active_username() -> str | None:
    """Return the username currently active on seat0, or None.

    Uses systemd-logind via `loginctl`. The "active" session is the one
    holding the local foreground console (graphical or text). Only seat0
    is considered — events can only physically come from the local
    keyboard, so a seat0 anchor is correct.
    """
    if FORCED_USER:
        return FORCED_USER
    try:
        sid = subprocess.check_output(
            ["loginctl", "show-seat", "seat0", "-p", "ActiveSession", "--value"],
            text=True, timeout=2,
        ).strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    if not sid:
        return None
    try:
        name = subprocess.check_output(
            ["loginctl", "show-session", sid, "-p", "Name", "--value"],
            text=True, timeout=2,
        ).strip()
    except subprocess.SubprocessError:
        return None
    return name or None


# username → UserContext, kept for the lifetime of the daemon.
_user_ctx_cache: dict[str, UserContext] = {}
_last_active_user: str | None = None


def get_active_context() -> UserContext | None:
    """Return the UserContext for whoever's active on seat0 right now.
    Invalidates the previous user's session env if the active user changed
    (so re-login picks up a fresh DISPLAY/XAUTHORITY)."""
    global _last_active_user

    user = get_active_username()
    if user is None:
        return None

    if user != _last_active_user and _last_active_user is not None:
        log(f"active user changed: {_last_active_user!r} → {user!r}")
        if _last_active_user in _user_ctx_cache:
            _user_ctx_cache[_last_active_user].invalidate_env()
    _last_active_user = user

    ctx = _user_ctx_cache.get(user)
    if ctx is None:
        try:
            ctx = UserContext(user)
        except KeyError:
            log(f"  ! loginctl reported unknown user {user!r}")
            return None
        _user_ctx_cache[user] = ctx
    return ctx


# ── action dispatch ───────────────────────────────────────────────────────────


def run_as_user(ctx: UserContext, argv: list[str], shell: bool = False,
                cmd: str | None = None) -> None:
    env = {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": ctx.home,
        "USER": ctx.username,
        "LOGNAME": ctx.username,
    }
    env.update(ctx.env)
    target_uid = ctx.uid
    target_gid = ctx.gid

    def preexec():
        os.setgid(target_gid)
        os.setuid(target_uid)

    try:
        if shell:
            assert cmd is not None
            proc = subprocess.Popen(
                ["/bin/sh", "-c", cmd], env=env, preexec_fn=preexec,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
        else:
            proc = subprocess.Popen(
                argv, env=env, preexec_fn=preexec,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
        try:
            out, err = proc.communicate(timeout=2)
            if proc.returncode != 0:
                log(f"  ! exited {proc.returncode}: {err.strip() or out.strip()}")
        except subprocess.TimeoutExpired:
            pass  # long-running, leave it
    except Exception as e:
        log(f"  ! dispatch error: {e}")


def run_action(ctx: UserContext, action: dict) -> None:
    t = action.get("type", "shell")
    if t == "noop":
        return
    if t == "shell":
        run_as_user(ctx, [], shell=True, cmd=action["cmd"])
    elif t == "exec":
        run_as_user(ctx, action["argv"], shell=False)
    elif t == "key":
        inject_key(action["code"], edge="tap")
    elif t == "key_down":
        inject_key(action["code"], edge="down")
    elif t == "key_up":
        inject_key(action["code"], edge="up")
    elif t == "notify":
        title = action.get("title", "")
        body = action.get("body", "")
        timeout = str(action.get("timeout_ms", 1500))
        run_as_user(ctx, ["notify-send", "-t", timeout, title, body], shell=False)
    else:
        log(f"  ! unknown action type {t!r}")


def normalize(binding) -> list[dict]:
    """Accept either a single action dict or a list."""
    if binding is None:
        return []
    if isinstance(binding, dict):
        return [binding]
    if isinstance(binding, list):
        return binding
    log(f"  ! invalid binding (expected dict or list): {binding!r}")
    return []


def dispatch(key: str, edge: str) -> None:
    """Look up the active user, load their config, run bindings."""
    ctx = get_active_context()
    if ctx is None:
        log(f"  -> {key}/{edge}: no active seat0 user, skipping")
        return
    config = ctx.load_config()
    actions = normalize(config.get(key, {}).get(edge))
    if not actions:
        log(f"  -> {key}/{edge}: ({ctx.username}, no binding)")
        return
    log(f"  -> {key}/{edge}: ({ctx.username}, {len(actions)} action(s))")
    for a in actions:
        run_action(ctx, a)


# ── main loop ─────────────────────────────────────────────────────────────────


def _dispatch_miap() -> None:
    try:
        buf = call_wed(0x80)
    except Exception as e:
        log(f"  ! _WED error: {e}")
        return
    evt0 = int.from_bytes(buf[0:2], "little")
    evt1 = int.from_bytes(buf[2:4], "little")
    # Group 0x0200 = macro keys (m1..m5 press 0x01-0x05 / release 0x06-0x0A).
    # Group 0x0100 = Fn+brightness level cycle (EVT1 = target brightness 0..5),
    #   collides with m-key codes; must NOT be dispatched as m-keys.
    if evt0 != 0x0200:
        log(f"  -> non-mkey group 0x{evt0:04x} EVT1=0x{evt1:02x} (ignored), raw={buf[:8].hex(' ')}")
        return
    mapping = EVT1_MAP.get(evt1)
    if mapping is None:
        log(f"  -> unknown EVT1=0x{evt1:02x}, raw={buf[:8].hex(' ')}")
        return
    dispatch(*mapping)


def _dispatch_fan(notify: int) -> None:
    if notify == 0xA2:
        dispatch("fan", "mode_a")
    elif notify == 0xA9:
        dispatch("fan", "mode_b")
    else:
        log(f"  -> unknown fan notify=0x{notify:02x}")


def handle_event(line: str) -> None:
    parts = line.split()
    if not parts:
        return

    # Kernel ≥6.10 format: "wmi PNP0C14:NN <notify_hex> <data_hex>"
    if parts[0] == "wmi" and len(parts) >= 3:
        device = parts[1]
        try:
            notify = int(parts[2], 16)
        except ValueError:
            return
        kind = PNP_TO_HANDLER.get(device)
        if kind == "miap_event":
            _dispatch_miap()
        elif kind == "fan_event":
            _dispatch_fan(notify)
        return

    # Legacy ≤6.9 format: "<GUID> <notify_hex> <data_hex>"
    guid = parts[0]
    if guid.startswith(GUID_MIAP_EVENT):
        _dispatch_miap()
    elif guid.startswith(GUID_FAN_MODE_A):
        dispatch("fan", "mode_a")
    elif guid.startswith(GUID_FAN_MODE_B):
        dispatch("fan", "mode_b")


def main() -> None:
    if os.geteuid() != 0:
        print("Run as root.", file=sys.stderr)
        sys.exit(1)

    log("mi-hotkey daemon started (multi-user mode).")
    log(f"  system config fallback: {SYSTEM_CONFIG_PATH}")
    log(f"  per-user config:        ~<user>/.config/mi-hotkey/config.toml")
    if FORCED_USER:
        log(f"  MI_HOTKEY_USER override active: dispatching as {FORCED_USER!r}")

    # Discover which PNP0C14:NN platform devices host our event GUIDs. Built
    # at startup (not module-import) so log() is available for diagnostics.
    global PNP_TO_HANDLER
    PNP_TO_HANDLER = discover_pnp_handlers()
    if not PNP_TO_HANDLER:
        log("WARNING: no event-firing WMI GUIDs discovered — no keys will dispatch")
    else:
        for pnp, kind in sorted(PNP_TO_HANDLER.items()):
            log(f"WMI handler bound: {pnp} → {kind}")

    # uinput is created lazily on first 'key*' action; we don't pre-warm it
    # here because configs are now resolved per-event (no startup-time view).

    proc = subprocess.Popen(
        ["acpi_listen"], stdout=subprocess.PIPE, text=True, bufsize=1
    )

    def shutdown(signum, frame):
        log("shutting down")
        proc.terminate()
        if _uinput is not None:
            try:
                _uinput.close()
            except Exception:
                pass
        sys.exit(0)

    def reload_config(signum, frame):
        log("SIGHUP received — invalidating per-user caches "
            "(configs are otherwise auto-reloaded on mtime change)")
        for ctx in _user_ctx_cache.values():
            ctx.invalidate_env()
            ctx._config_mtime = None  # force re-read on next event

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGHUP, reload_config)

    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        log(f"event: {line}")
        try:
            handle_event(line)
        except Exception as e:
            log(f"  ! handler error: {e}")


if __name__ == "__main__":
    main()
