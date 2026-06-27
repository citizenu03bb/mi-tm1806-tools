#!/bin/bash
# keyboard-status.sh -- Claude Code hook handler that paints the bar zone
# (LEDZ=04) on the Mi TM1806 keyboard to reflect Claude Code session state.
#
# Single-shot. Invoked once per hook event by Claude Code. Reads the event
# name as $1 (passed explicitly from settings.json so we don't need to parse
# JSON for basic dispatch). Other zones (left/mid/right) are NEVER touched.
#
# Caveat: any paint resets the global LETY register (firmware-level, see
# driver/README.md). If you have breath/wave running on the other three
# zones, this script will NOT change effect, so they keep animating; but
# the bar's color is what you set here, and a fresh paint snapshots that
# color into bar's per-zone SRAM.
#
# Disable temporarily:  export CLAUDE_KB_STATUS_DISABLE=1
# Disable persistently: touch ~/.claude-keyboard.off
#
# Requires: kernel driver loaded (mi_tm1806_led) AND user write access to
# the sysfs nodes (see ../99-mi-tm1806-led.rules).

set -u

# --- escape hatches ---
[ "${CLAUDE_KB_STATUS_DISABLE:-0}" = "1" ] && exit 0
[ -f "$HOME/.claude-keyboard.off" ] && exit 0

LED=/sys/class/leds/mi_tm1806::kbd_bar
WMI=/sys/bus/wmi/devices/E2A89D40-784F-4E91-BE22-AE373CDEA97A

# Driver not loaded -> silent no-op.
[ -d "$LED" ] || exit 0

FADE_STEPS=8
FADE_SLEEP=0.025

# fade [<r> <g> <b>] <target_brightness>
#   4 args: stage new color, then ramp brightness from current to target.
#   1 arg : ramp brightness only (keep color). Used for fade-to-off.
#
# The firmware has no one-shot fade primitive; LETY=2 (breath) is continuous,
# not transient. So we drive the brightness ourselves in small steps. Each
# step writes /brightness which triggers a full paint inside the kernel
# driver (~30 ms), so the actual fade duration is ~200-400 ms — slow enough
# to look smooth, fast enough not to be felt.
fade() {
	local r g b target
	if [ "$#" -eq 4 ]; then
		r=$1; g=$2; b=$3; target=$4
		echo "$r $g $b" > "$LED/multi_intensity" 2>/dev/null || return 0
	else
		target=$1
	fi

	local cur
	cur=$(cat "$LED/brightness" 2>/dev/null || echo 0)
	local diff=$((target - cur))
	[ "$diff" -eq 0 ] && return 0

	local i val
	for ((i=1; i<=FADE_STEPS; i++)); do
		val=$((cur + diff * i / FADE_STEPS))
		echo "$val" > "$LED/brightness" 2>/dev/null || return 0
		sleep "$FADE_SLEEP"
	done
}

# --- color map ---
# Brightnesses kept low on purpose: dim/active/attention = 24/64/120. The
# bar is in your peripheral vision, not center stage; saturating it makes
# every transition flashy, which gets old fast (and isn't friendly to
# photosensitive viewers). If you want it more visible, tweak here.
case "${1:-}" in
	SessionStart)
		fade  64  64  64  24 ;;	# dim white -- "ready"
	UserPromptSubmit)
		fade   0 102 255  64 ;;	# soft blue -- received your input
	PreToolUse)
		fade   0 102 255  64 ;;	# soft blue -- tool running
	PostToolUse)
		fade  64  64  64  24 ;;	# dim white -- between tools
	Notification)
		fade 255 153   0 120 ;;	# medium amber -- needs attention
	Stop)
		fade 0 ;;			# fade out -- turn done
	SessionEnd)
		fade 0 ;;
	*)
		# Unknown event or no arg; do nothing.
		;;
esac
exit 0
