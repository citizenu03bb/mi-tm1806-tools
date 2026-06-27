#!/bin/bash
# keyboard-status.sh -- Claude Code hook handler that paints the bar zone
# (LEDZ=04) on the Mi TM1806 keyboard to reflect Claude Code session state.
#
# Single-shot. Invoked once per hook event by Claude Code. Reads the event
# name as $1. Other zones (left/mid/right) are NEVER touched.
#
# Uses the kernel driver's store-and-commit model: writes multi_intensity
# and brightness for the bar zone, then calls `commit` to batch-paint all
# zones. Other zones keep whatever colours the driver last stored for them.
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

# paint <r> <g> <b> [brightness]
#   Store the colour + brightness for the bar zone, then commit so the
#   kernel driver batch-paints all zones with their last-stored values.
#   Off: pass "0 0 0" with no brightness (brightness stays 0 → black).
paint() {
	local r=$1 g=$2 b=$3 bright="${4:-255}"
	echo "$r $g $b" > "$LED/multi_intensity" 2>/dev/null || return 0
	echo "$bright" > "$LED/brightness" 2>/dev/null || return 0
	echo 1 > "$WMI/commit" 2>/dev/null || return 0
}

# --- color map ---
# Brightnesses kept low on purpose: dim/active/attention = 24/64/120.
# The bar is in your peripheral vision, not center stage.
case "${1:-}" in
	SessionStart)
		paint  64  64  64  24 ;;	# dim white -- "ready"
	UserPromptSubmit)
		paint   0 102 255  64 ;;	# soft blue -- received your input
	PreToolUse)
		paint   0 102 255  64 ;;	# soft blue -- tool running
	PostToolUse)
		paint  64  64  64  24 ;;	# dim white -- between tools
	Notification)
		paint 255 153   0 120 ;;	# medium amber -- needs attention
	Stop)
		paint   0   0   0   0 ;;	# off -- turn done
	SessionEnd)
		paint   0   0   0   0 ;;
	*)
		;;
esac
exit 0
