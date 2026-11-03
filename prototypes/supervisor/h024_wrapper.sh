#!/bin/sh
# H-024 SOURCE-ONLY OFFLINE supervisor wrapper.
# It cannot invoke the device, procd or an actual PON configuration reader.
set -u
umask 077

if [ "$#" -ne 7 ] || [ "$1" != "offline_synthetic" ]; then
    echo "H024_SOURCE_ONLY_MODE_REQUIRED" >&2
    exit 64
fi
qemu=$2
rootfs=$3
history=$4
overlay=$5
runtime=$6
worker=$7

# The test-only lock directory is independently provisioned by the harness.
# All arguments are paths, not interpreted commands or script fragments.
case "$runtime" in
  /var/tmp/aott-h022-lock-test-[A-Za-z0-9-]*)
    ;;
  *)
    echo "H024_UNAPPROVED_RUNTIME_DIRECTORY" >&2
    exit 65
    ;;
esac
for path in "$qemu" "$rootfs" "$history" "$overlay" "$runtime" "$worker"; do
    case "$path" in
      /*) ;;
      *) echo "H024_RELATIVE_PATH_REJECTED" >&2; exit 66 ;;
    esac
    case "$path" in
      *..*|*" "*|*[\;\|\&\$\`\>\<\(\)\{\}]*)
        echo "H024_UNSAFE_PATH_REJECTED" >&2
        exit 66
        ;;
    esac
done
[ -x "$qemu" ] && [ -x "$rootfs/usr/bin/lua" ] &&
[ -r "$worker" ] && [ -d "$runtime" ] || {
    echo "H024_REQUIRED_OFFLINE_SOURCE_MISSING" >&2
    exit 67
}
[ "$(id -u)" -eq 0 ] || {
    echo "H024_TEST_RUNTIME_REQUIRES_ROOT" >&2
    exit 68
}
stopfile="$runtime/stop.$$.request"
[ ! -e "$stopfile" ] && [ ! -L "$stopfile" ] || {
    echo "H024_EXISTING_STOP_MARKER" >&2
    exit 69
}

# No core files, at most 32 file descriptors and 4 GiB virtual address space in offline QEMU (NOT board RAM budget).
# These are candidate limits, NOT approved production resource budgets.
ulimit -c 0 || exit 70
ulimit -n 32 || exit 70
ulimit -v 4194304 || exit 70

# Keep a normal-priority shell wrapper so it can respond to a shutdown,
# and lower the test worker's CPU scheduling priority.
nice -n 10 "$qemu" -L "$rootfs" "$rootfs/usr/bin/lua" "$worker" \
    offline_synthetic "$rootfs" "$history" "$overlay" "$runtime" \
    "$stopfile" "$$" &
child=$!

shutdown() {
    trap '' TERM INT HUP
    : > "$stopfile" || {
        kill -TERM "$child" 2>/dev/null || :
    }
    seconds=0
    while kill -0 "$child" 2>/dev/null && [ "$seconds" -lt 5 ]; do
        sleep 1
        seconds=$((seconds + 1))
    done
    if kill -0 "$child" 2>/dev/null; then
        kill -TERM "$child" 2>/dev/null || :
        sleep 1
    fi
    if kill -0 "$child" 2>/dev/null; then
        kill -KILL "$child" 2>/dev/null || :
    fi
    wait "$child" 2>/dev/null || :
    rm -f "$stopfile"
    echo "AOTT_H024_OFFLINE_WRAPPER_STOPPED"
    exit 0
}
trap shutdown TERM INT HUP
if wait "$child"; then
    result=0
else
    result=$?
fi
trap - TERM INT HUP
rm -f "$stopfile"
if [ "$result" -ne 0 ]; then
    echo "AOTT_H024_OFFLINE_WORKER_EXITED_NONZERO" >&2
fi
exit "$result"
