#!/bin/sh
# AoTT C-011: read only exact built-in flower rule content through tc.
# Only a fixed, validated native reconciler plan is accepted as argv.
# No services are restarted and no tc add/del/replace/flush is called.
# This checks selected owned kernel rules, NOT ISP/WAN availability,
# line rate, unknown priorities, or end-to-end hardware forwarding.
set -eu

[ "$#" -eq 7 ] || exit 64
internet=$1
services=$2
unicast=$3
pmap_inet=$4
pmap_services=$5
olt_services=$6
multicast=$7

vlan() {
    case "$1" in ''|*[!0-9]*) return 1;; esac
    case "$1" in ?|??|???|????) ;; *) return 1;; esac
    [ "$1" -ge "$2" ] && [ "$1" -le 4095 ]
}
pmapper() {
    case "$1" in pmapper*) ;; *) return 1;; esac
    suffix=$(printf %s "$1" | sed 's/^pmapper//')
    case "$suffix" in ''|*[!0-9]*) return 1;; esac
    case "$suffix" in ?|??|???|????|?????|??????|???????|????????) ;; *) return 1;; esac
}

vlan "$internet" 0 || exit 64
vlan "$services" 1 || exit 64
vlan "$unicast" 1 || exit 64
pmapper "$pmap_inet" || exit 64
[ "$internet" != "$services" ] || exit 64
case "$multicast" in 0|1) ;; *) exit 64;; esac
if [ "$pmap_services" = "-" ]; then
    [ "$olt_services" = "-" ] && [ "$multicast" = 0 ] || exit 64
else
    pmapper "$pmap_services" || exit 64
    [ "$pmap_services" != "$pmap_inet" ] || exit 64
    vlan "$olt_services" 1 || exit 64
fi

[ -r /lib/8311-vlans-lib.sh ] || exit 69
. /lib/8311-vlans-lib.sh || exit 69
command -v tc_flower_matches >/dev/null 2>&1 || exit 69

count=0
check() {
    tc_flower_matches "$@" || exit 1
    count=$((count+1))
}

if [ "$internet" -eq 0 ]; then
    check dev "$pmap_inet" ingress handle 0x1 protocol 802.1Q pref 1 flower skip_sw action vlan pop pass
    check dev "$pmap_inet" egress handle 0x1 protocol 802.1Q pref 1 flower skip_sw action drop
    check dev "$pmap_inet" egress handle 0x2 protocol all pref 2 flower skip_sw action vlan push id "$unicast" priority 0 protocol 802.1Q pass
else
    check dev "$pmap_inet" ingress handle 0x1 protocol 802.1Q pref 1 flower skip_sw action vlan modify id "$internet" protocol 802.1Q pass
    check dev "$pmap_inet" egress handle 0x1 protocol 802.1Q pref 1 flower vlan_id "$internet" skip_sw action vlan modify id "$unicast" protocol 802.1Q pass
    check dev "$pmap_inet" egress handle 0x2 protocol 802.1Q pref 2 flower skip_sw action drop
    check dev "$pmap_inet" egress handle 0x3 protocol all pref 3 flower skip_sw action drop
fi

if [ "$pmap_services" != "-" ]; then
    check dev "$pmap_services" ingress handle 0x1 protocol 802.1Q pref 1 flower skip_sw action vlan modify id "$services" protocol 802.1Q pass
    check dev "$pmap_services" egress handle 0x1 protocol 802.1Q pref 1 flower vlan_id "$services" skip_sw action vlan modify id "$olt_services" protocol 802.1Q pass
    check dev "$pmap_services" egress handle 0x2 protocol 802.1Q pref 2 flower skip_sw action drop
    check dev "$pmap_services" egress handle 0x3 protocol all pref 3 flower skip_sw action drop
    if [ "$multicast" -eq 1 ]; then
        check dev eth0_0_2 egress handle 0x1 protocol 802.1Q pref 1 flower skip_sw action vlan modify id "$services" priority 5 protocol 802.1Q pass
    fi
fi

# Exact, constant-format count only. No raw rules, interfaces, VLANs or
# subscriber data are exposed in this output.
printf 'VERIFIED_RULES=%s\n' "$count"
