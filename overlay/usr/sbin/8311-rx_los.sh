#!/bin/sh
PIN=505

_lib_8311 2>/dev/null || . /lib/8311.sh

STATE_DIR=/var/run/aott-runtime
STATE_FILE=$STATE_DIR/rxlos.state

state_write() {
    local enabled="$1" active="$2" tmp boot_id
    boot_id=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null) || return 1
    [ -n "$boot_id" ] || return 1
    umask 077
    if [ -L "$STATE_DIR" ] || { [ -e "$STATE_DIR" ] && [ ! -d "$STATE_DIR" ]; }; then
        return 1
    fi
    [ -d "$STATE_DIR" ] || mkdir -m 700 "$STATE_DIR" || return 1
    chmod 700 "$STATE_DIR" || return 1
    [ ! -L "$STATE_FILE" ] || return 1
    tmp="$STATE_FILE.new.$$"
    rm -f "$tmp"
    {
        printf 'schema=1\n'
        printf 'pid=%s\n' "$$"
        printf 'boot_id=%s\n' "$boot_id"
        printf 'enabled=%s\n' "$enabled"
        printf 'active=%s\n' "$active"
    } > "$tmp" || { rm -f "$tmp"; return 1; }
    chmod 600 "$tmp" || { rm -f "$tmp"; return 1; }
    mv -f "$tmp" "$STATE_FILE" || { rm -f "$tmp"; return 1; }
}

state_clear() {
    [ ! -L "$STATE_FILE" ] || return 0
    [ -f "$STATE_FILE" ] || return 0
    grep -qx "pid=$$" "$STATE_FILE" 2>/dev/null && rm -f "$STATE_FILE"
}
trap state_clear EXIT HUP INT TERM

GPIO="/sys/class/gpio/gpio${PIN}"
[ -d "$GPIO" ] || echo "$PIN" > "/sys/class/gpio/export"

RX_LOS=$(fwenv_get_8311 "rx_los")
[ "$RX_LOS" -ne 0 ] 2>/dev/null && RX_LOS=true || RX_LOS=false

if $RX_LOS; then
    state_write 1 1 || {
        echo "8311 RX_LOS daemon: unable to publish runtime state" | to_console
        exit 1
    }
    echo "8311 RX_LOS daemon: start monitoring LOS alarm" | to_console
    while true; do
        LOS_VALUE=0
        IFS= read -r LOS_VALUE < "$GPIO/value" || LOS_VALUE=0
        LOS_ALARM=$([ -d "/sys/devices/virtual/net/gem-omci" ] && { pon alarm_status_get 0 | grep -E -o 'alarm_status=\d+' | cut -d= -f2; } || echo "0")

        if [ "$LOS_VALUE" -ne "$LOS_ALARM" ] 2>/dev/null; then
            [ "$LOS_ALARM" -eq 1 ] 2>/dev/null && GPIO_DIR="high" || GPIO_DIR="low"
            echo "8311 RX_LOS daemon: setting RX_LOS pin to $GPIO_DIR" | to_console
            echo "$GPIO_DIR" > "$GPIO/direction"
        fi
        sleep 3
    done
else
    state_write 0 0 || {
        echo "8311 RX_LOS daemon: unable to publish runtime state" | to_console
        exit 1
    }
    echo "8311 RX_LOS daemon: start disabling RX_LOS" | to_console
    while true; do
        LOS_VALUE=0
        IFS= read -r LOS_VALUE < "$GPIO/value" || LOS_VALUE=0
        if [ "$LOS_VALUE" -ne 0 ] 2>/dev/null; then
            echo "8311 RX_LOS daemon: setting RX_LOS pin to low" | to_console
            echo "low" > "$GPIO/direction"
        fi
        sleep 1
    done
fi
