#!/bin/sh
_lib_8311 2>/dev/null || . /lib/8311.sh

STATE_DIR=/var/run/aott-runtime
STATE_FILE=$STATE_DIR/rarpd.state
STATE_LAST=

state_write() {
    local enabled="$1" active="$2" tmp boot_id current
    current="$enabled|$active"
    if [ "$STATE_LAST" = "$current" ] && [ -f "$STATE_FILE" ] && [ ! -L "$STATE_FILE" ]; then
        return 0
    fi
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
    STATE_LAST="$current"
}

state_clear() {
    [ ! -L "$STATE_FILE" ] || return 0
    [ -f "$STATE_FILE" ] || return 0
    grep -qx "pid=$$" "$STATE_FILE" 2>/dev/null && rm -f "$STATE_FILE"
}
trap state_clear EXIT HUP INT TERM

echo "8311 Reverse ARP daemon: start monitoring" | to_console
while true; do
    RARP_ENABLED=$(fwenv_get_8311 "reverse_arp" "1")
    myip=$(ip -o -4 a list dev eth0_0_1_lct | pcre2grep -o1 ' inet (\d+\.\d+\.\d+\.\d+)/')
    if [ -n "$myip" ] && [ "$RARP_ENABLED" -ne 0 ] 2>/dev/null &&
       [ "$(cat /sys/class/net/eth0_0_1_lct/carrier 2>/dev/null)" -eq 1 ] 2>/dev/null; then
        state_write 1 1 || {
            echo "8311 rarpd: unable to publish runtime state" | to_console
            exit 1
        }
        IFS='.' read -r i1 i2 i3 i4 <<IPADDR
$myip
IPADDR
        tcpdump -lKpenNq -Q 'in' -tt -i 'eth0_0_1_lct' \
          "(arp and arp[7]=1 and arp[24]=$i1 and arp[25]=$i2 and arp[26]=$i3 and arp[27]=$i4) or (dst host $myip)" 2>/dev/null |
        pcre2grep --line-buffered -o1 -o2 -o3 --om-separator ' ' \
          '^(\d+)\.\d+ (\S+) > \S+, \S+, length \d+: (?:.+? tell )?(\d+\.\d+\.\d+\.\d+)' |
        awk '{
            ip=$3; mac=$2; time=$1
            if (!macs[ip] || !times[ip] || macs[ip] != mac || (time-times[ip]) > 15) {
                macs[ip]=mac; times[ip]=time
                print time,mac,ip
            }
        }' |
        while IFS=' ' read -r seen mac ipaddr; do
            case "$mac" in
                [0-9A-Fa-f][0-9A-Fa-f]:[0-9A-Fa-f][0-9A-Fa-f]:[0-9A-Fa-f][0-9A-Fa-f]:[0-9A-Fa-f][0-9A-Fa-f]:[0-9A-Fa-f][0-9A-Fa-f]:[0-9A-Fa-f][0-9A-Fa-f]) ;;
                *) continue ;;
            esac
            printf '%s\n' "$ipaddr" | ipv4 >/dev/null || continue
            ip neigh replace dev eth0_0_1_lct to "$ipaddr" lladdr "$mac" nud reachable
        done
        sleep 1
    else
        if [ "$RARP_ENABLED" -ne 0 ] 2>/dev/null; then RARP_CONFIGURED=1; else RARP_CONFIGURED=0; fi
        state_write "$RARP_CONFIGURED" 0 || {
            echo "8311 rarpd: unable to publish runtime state" | to_console
            exit 1
        }
        sleep 30
    fi
done
