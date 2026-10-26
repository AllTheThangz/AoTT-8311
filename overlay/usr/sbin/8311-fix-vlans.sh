#!/bin/sh
# The daemon and GUI hook editor serialize through /tmp/8311-fix-vlans.lock.
# Stage detected state; publish it only after every owned rule reads back.
DETECT_CONFIG=/usr/sbin/8311-detect-config.sh
CONFIG_FILE=/tmp/8311-config.sh
. /lib/8311-vlans-lib.sh || exit 69
UNICAST_IFACE=eth0_0
MULTICAST_IFACE=eth0_0_2
umask 077
work=
cleanup() {
    status=$?
    trap - EXIT HUP INT TERM
    [ -z "$work" ] || rm -rf "$work"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
fail() { printf 'VLAN reconciliation: %s\n' "$1" >&2; exit 1; }

valid_config() {
    [ ! -L "$1" ] && [ -f "$1" ] || return 1
    [ "$(stat -c '%u' "$1")" = "$(id -u)" ] || return 1
    case "$(stat -c '%a' "$1")" in *[2367][0-7]|*[0-7][2367]) return 1;; esac
    [ "$(stat -c '%s' "$1")" -le 4096 ] || return 1
    # Configuration is data, never arbitrary shell. Reject metacharacters,
    # unknown assignments and additional commands before sourcing it.
    LC_ALL=C awk '
        /^[[:space:]]*(#|$)/ { next }
        /^(FIX_ENABLED|UNICAST_VLAN|MULTICAST_GEM|INTERNET_PMAP|INTERNET_GEMS|SERVICES_PMAP|SERVICES_GEMS|INTERNET_VLAN|SERVICES_VLAN|DEFAULT_SERVICES_VLAN|STATE_HASH)=[a-zA-Z0-9_.:-]*$/ { next }
        /^(INTERNET_GEMS|SERVICES_GEMS)="[a-zA-Z0-9_.: -]*"$/ { next }
        { bad=1 }
        END { exit bad ? 1 : 0 }
    ' "$1"
}
reset_config() {
    STATE_HASH= FIX_ENABLED= INTERNET_VLAN= UNICAST_VLAN= INTERNET_PMAP=
    SERVICES_VLAN= DEFAULT_SERVICES_VLAN= SERVICES_PMAP= MULTICAST_GEM= INTERNET_GEMS= SERVICES_GEMS=
}
valid_vlan() {
    case "$1" in ''|*[!0-9]*) return 1;; esac
    [ "$1" -ge "$2" ] && [ "$1" -le 4095 ]
}
valid_iface() {
    case "$1" in ''|*[!a-zA-Z0-9_.:-]*) return 1;; esac
    [ "${#1}" -le 15 ]
}
valid_rules_config() {
    valid_vlan "$INTERNET_VLAN" 0 && valid_vlan "$UNICAST_VLAN" 1 && valid_iface "$INTERNET_PMAP" || return 1
    if [ -n "$SERVICES_PMAP" ]; then
        valid_iface "$SERVICES_PMAP" && valid_vlan "$SERVICES_VLAN" 1 && valid_vlan "$DEFAULT_SERVICES_VLAN" 1 || return 1
        [ "$SERVICES_PMAP" != "$INTERNET_PMAP" ] || return 1
    fi
    [ -z "$MULTICAST_GEM" ] || valid_iface "$MULTICAST_GEM"
}
rules() {
    if [ "$INTERNET_VLAN" -ne 0 ]; then
        printf 'dev %s ingress handle 0x1 protocol 802.1Q pref 1 flower skip_sw action vlan modify id %s protocol 802.1Q pass\n' "$INTERNET_PMAP" "$INTERNET_VLAN"
        printf 'dev %s egress handle 0x1 protocol 802.1Q pref 1 flower vlan_id %s skip_sw action vlan modify id %s protocol 802.1Q pass\n' "$INTERNET_PMAP" "$INTERNET_VLAN" "$UNICAST_VLAN"
        printf 'dev %s egress handle 0x2 protocol 802.1Q pref 2 flower skip_sw action drop\n' "$INTERNET_PMAP"
        printf 'dev %s egress handle 0x3 protocol all pref 3 flower skip_sw action drop\n' "$INTERNET_PMAP"
    else
        printf 'dev %s ingress handle 0x1 protocol 802.1Q pref 1 flower skip_sw action vlan pop pass\n' "$INTERNET_PMAP"
        printf 'dev %s egress handle 0x1 protocol 802.1Q pref 1 flower skip_sw action drop\n' "$INTERNET_PMAP"
        printf 'dev %s egress handle 0x2 protocol all pref 2 flower skip_sw action vlan push id %s priority 0 protocol 802.1Q pass\n' "$INTERNET_PMAP" "$UNICAST_VLAN"
    fi
    if [ -n "$SERVICES_PMAP" ]; then
        printf 'dev %s ingress handle 0x1 protocol 802.1Q pref 1 flower skip_sw action vlan modify id %s protocol 802.1Q pass\n' "$SERVICES_PMAP" "$SERVICES_VLAN"
        printf 'dev %s egress handle 0x1 protocol 802.1Q pref 1 flower vlan_id %s skip_sw action vlan modify id %s protocol 802.1Q pass\n' "$SERVICES_PMAP" "$SERVICES_VLAN" "$DEFAULT_SERVICES_VLAN"
        printf 'dev %s egress handle 0x2 protocol 802.1Q pref 2 flower skip_sw action drop\n' "$SERVICES_PMAP"
        printf 'dev %s egress handle 0x3 protocol all pref 3 flower skip_sw action drop\n' "$SERVICES_PMAP"
        if [ -n "$MULTICAST_GEM" ]; then
            printf 'dev %s egress handle 0x1 protocol 802.1Q pref 1 flower skip_sw action vlan modify id %s priority 5 protocol 802.1Q pass\n' "$MULTICAST_IFACE" "$SERVICES_VLAN"
        fi
    fi
}

[ -x "$DETECT_CONFIG" ] || fail 'detection script unavailable'
work=$(mktemp -d /tmp/8311-vlans.XXXXXX) || fail 'cannot create workspace'
reset_config
: > "$work/old-rules"
if [ -e "$CONFIG_FILE" ] || [ -L "$CONFIG_FILE" ]; then
    valid_config "$CONFIG_FILE" || fail 'stored configuration is invalid'
    . "$CONFIG_FILE"
    [ "$FIX_ENABLED" != 0 ] || exit 69
    valid_rules_config || fail 'stored rule configuration is invalid'
    rules > "$work/old-rules" || fail 'cannot record previous rules'
fi
old_hash=$STATE_HASH
new_hash=$("$DETECT_CONFIG" -H) || fail 'cannot read configuration state'
[ -n "$new_hash" ] || fail 'empty configuration state'
if [ ! -f "$CONFIG_FILE" ] || [ "$new_hash" != "$old_hash" ]; then
    "$DETECT_CONFIG" -c "$work/config" >/dev/null || fail 'configuration detection failed'
else
    cp "$CONFIG_FILE" "$work/config" || fail 'cannot stage current configuration'
fi
valid_config "$work/config" || fail 'detected configuration is invalid'
reset_config
. "$work/config"
[ "$FIX_ENABLED" != 0 ] || exit 69
valid_rules_config || fail 'detected rule configuration is invalid'
[ "$STATE_HASH" = "$new_hash" ] || fail 'configuration changed during detection'
rules > "$work/rules" || fail 'cannot stage desired rules'
while IFS= read -r rule; do
    tc_flower_selector $rule || exit 1
done < "$work/rules" > "$work/selectors" || fail 'invalid desired selector'

# Remove only obsolete selectors from the last successful builtin rule set.
# Custom priorities/handles and unrelated interfaces are left untouched.
while IFS= read -r rule; do
    selector=$(tc_flower_selector $rule) || fail 'invalid old selector'
    if ! grep -Fxq "$selector" "$work/selectors"; then
        tc_flower_del $rule || fail 'could not remove obsolete owned rule'
    fi
done < "$work/old-rules"
while IFS= read -r rule; do
    tc_flower_ensure $rule || fail 'rule replacement or content verification failed'
done < "$work/rules"
# A later rule must not silently alter an earlier one. Verify the full set.
while IFS= read -r rule; do
    tc_flower_matches $rule || fail 'final rule-set verification failed'
done < "$work/rules"
after_hash=$("$DETECT_CONFIG" -H) || fail 'cannot verify final configuration state'
[ "$after_hash" = "$new_hash" ] || fail 'configuration changed during reconciliation'
chmod 600 "$work/config" && mv -fT "$work/config" "$CONFIG_FILE" || fail 'cannot commit verified configuration'
printf '%s\n' 'VLAN rules verified; configuration committed'
exit 0
