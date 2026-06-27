# Claude Code → keyboard status indicator

Drives the **bar zone** (LEDZ=04, the hotkey strip above the keyboard) as a status surface for a Claude Code session. Other zones are never touched, so anything you have running on left/mid/right (solid color, breath, wave) keeps going.

## What you see

### Default (in `settings.json.snippet`)

| Hook event           | Bar color                  | Meaning                                              |
|----------------------|----------------------------|------------------------------------------------------|
| `SessionStart`       | dim white (24)             | session ready                                        |
| `Notification`       | **medium amber (120)**     | awaiting permission / idle warning                   |
| `Stop`               | off                        | turn done                                            |
| `SessionEnd`         | off                        | session closed                                       |

The interesting transition is **dim-white → amber**: that's Claude waiting for you. Easy to spot from your peripheral vision without alt-tabbing back to the terminal.

### Optional events (handled by the script, not wired up by default)

`UserPromptSubmit`, `PreToolUse`, `PostToolUse` are implemented in `keyboard-status.sh` (soft blue at brightness 64 for active, dim white at 24 for between-tools) but **not** in the default `settings.json.snippet` because they fire often and the extra blinking gets old fast. Add the corresponding entries to your settings.json if you want a more talkative bar.

Brightnesses are intentionally low (24 / 64 / 120 out of 255) so transitions are unobtrusive and not unkind to photosensitive viewers. Edit `keyboard-status.sh` if you want it more visible.

## Installation

Three steps. None automatic.

### 1. udev rule (so the user can write to sysfs without sudo)

```sh
sudo cp 99-mi-tm1806-led.rules /etc/udev/rules.d/
sudo udevadm control --reload
sudo rmmod mi_tm1806_led && sudo modprobe mi_tm1806_led
```

That second command reloads the driver so the new udev rule fires the `add` action and chgrps the sysfs files to `plugdev`. (`udevadm trigger` alone won't re-fire `add` for an existing device on every kernel.)

Verify:

```sh
ls -l /sys/class/leds/mi_tm1806::kbd_bar/{brightness,multi_intensity}
```

Should show group `plugdev` with `g+w`. You need to be in `plugdev` (`groups | grep plugdev`); on most desktop installs you already are.

### 2. Hook script

Already executable from this repo path. If you'd rather have it under `~/.claude/`:

```sh
mkdir -p ~/.claude/hooks
cp keyboard-status.sh ~/.claude/hooks/
chmod +x ~/.claude/hooks/keyboard-status.sh
```

…and adjust the paths in step 3 accordingly. The default snippet below points at the in-repo path.

### 3. Wire up `~/.claude/settings.json`

Merge `settings.json.snippet` into your existing `~/.claude/settings.json`. If you have no existing `hooks` block, just paste the snippet's `hooks` value under your top-level object. If you already have hooks, add the events under the existing `hooks` key.

Reload by starting a new Claude Code session — settings.json is read at session start.

## Disabling

Three escape hatches, in order of friction:

```sh
export CLAUDE_KB_STATUS_DISABLE=1     # one shell only, transient
touch ~/.claude-keyboard.off          # persistent, all sessions
# or just remove the entries from ~/.claude/settings.json
```

The script checks both env var and marker file before doing anything.

## Trade-offs to know about

- **All paints stop the global animation.** The Mi firmware has one `LETY` register shared across zones (see `driver/README.md`). The hook script does NOT change `effect`, only `multi_intensity` and `brightness` — so left/mid/right keep whatever animation you set. But the **bar** zone will display its new static color until you switch effect manually.
- **Hook latency on tool calls.** `PreToolUse` is sync. The bar paint is ~30 ms (one `acpi_evaluate_integer` for KBBR + one WMI write for stage_c + one for LightEffect). On most workloads this is invisible; in tight tool-call loops it adds up. If it gets annoying, you can drop the `PreToolUse` / `PostToolUse` entries from settings.json and keep just the higher-signal ones (`Notification`, `Stop`, `SessionStart`).
- **Cold-boot panel-off case.** If `KBBR=5` (panel power-gated, requires Fn+brightness once to wake), the kernel driver returns `-ENXIO` from every `multi_intensity` write. The hook script silently ignores write failures — no errors propagated to the Claude Code session.

## Future-work ideas (not built)

- Use the `Notification` payload's stdin JSON to distinguish *permission prompt* (red?) from *idle warning* (amber).
- Track tool-call duration in a state file: if `PreToolUse` → `PostToolUse` exceeds N seconds, escalate bar color (e.g., blue → cyan → magenta). Useful for "is this build still running?".
- Per-permission-mode color: in `bypassPermissions` mode (auto), tint the bar slightly differently than in `default`.
- A second zone (e.g., kb-left) reserved as an "agent-thinking-load" indicator driven by token-rate or tool-frequency.
