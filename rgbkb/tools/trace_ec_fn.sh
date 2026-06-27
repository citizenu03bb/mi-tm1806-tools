#!/bin/bash
# Trace ALL host-side EC traffic during Fn+brightness presses.
# Captures kprobes on acpi_ec_gpe_handler (SCI from EC), acpi_ec_transaction
# (port 62/66 I/O), and acpi_ec_space_handler (ACPI EC operation region access)
# for 30 seconds while the user presses Fn+brightness several times.
#
# Interpretation:
#   - If gpe_handler fires only AFTER each Fn press → EC notifies passively;
#     painter is fully internal, host has no observable trigger.
#   - If transaction or space_handler also fires → ACPI is querying EC RAM,
#     and we should look at WHERE in the call stack to find the trigger.
#   - If a function fires BEFORE the Fn press effect (i.e., paint precedes
#     gpe), the trigger is in something else.
#
# Usage: sudo ./trace_ec_fn.sh
set -euo pipefail
[ "$EUID" -eq 0 ] || { echo "run as root"; exit 1; }

out=/tmp/ec_trace.log
: > "$out"

echo "Starting bpftrace for 30s. PRESS Fn+keyboard-brightness 3-5 times during this window."
echo "Trace output → $out"
echo

bpftrace -e '
BEGIN { printf("[trace started; press Fn now]\n"); }
kprobe:acpi_ec_transaction        { @["transaction"] = count(); printf("%s acpi_ec_transaction\n", strftime("%H:%M:%S.%f", nsecs)); }
kprobe:acpi_ec_transaction_unlocked { @["transaction_unlocked"] = count(); }
kprobe:acpi_ec_gpe_handler        { @["gpe_handler"] = count(); printf("%s acpi_ec_gpe_handler\n", strftime("%H:%M:%S.%f", nsecs)); }
kprobe:acpi_ec_space_handler      { @["space_handler"] = count(); printf("%s acpi_ec_space_handler\n", strftime("%H:%M:%S.%f", nsecs)); }
END { printf("\n=== summary counters ===\n"); print(@); }
' 2>&1 | tee -a "$out" &
TRACE_PID=$!

sleep 30
kill -INT $TRACE_PID 2>/dev/null || true
wait $TRACE_PID 2>/dev/null || true

echo
echo "=== trace summary ==="
grep -c "acpi_ec_gpe_handler" "$out" | xargs -I{} echo "gpe_handler fires: {}"
grep -c "acpi_ec_transaction" "$out" | xargs -I{} echo "transaction fires: {}"
grep -c "acpi_ec_query" "$out" | xargs -I{} echo "query fires: {}"
echo
echo "Full trace: $out"
