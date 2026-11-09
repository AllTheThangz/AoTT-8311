#!/bin/sh

_lib_8311 2>/dev/null || . /lib/8311.sh

pon_hash() {
	/usr/sbin/8311-detect-config.sh -H
}

FIX_ENABLED=$(fwenv_get_8311 "fix_vlans" "1")
case "$FIX_ENABLED" in
    0)
        /usr/sbin/8311-fix-vlans.sh --clear-owned || exit 1
        exit 0
        ;;
    1) ;;
    2)
        # Hook-only mode must not inherit stale selectors from the built-in
        # reconciler. The hook owns any rules it deliberately creates.
        /usr/sbin/8311-fix-vlans.sh --clear-owned || exit 1
        ;;
    *) exit 1 ;;
esac

HOOK="/ptconf/8311/vlan_fixes_hook.sh"

FIXES=""
[ "$FIX_ENABLED" -eq 1 ] && FIXES="/usr/sbin/8311-fix-vlans.sh"
HOOKCMD=". /lib/8311-vlans-lib.sh && . $HOOK"

LAST_HASH=""

echo "8311 VLANs daemon: start monitoring" | to_console
while true ; do
	[ -f "$HOOK" ] && { [ -n "$FIXES" ] && CMD="$FIXES && $HOOKCMD" || CMD="$HOOKCMD"; } || CMD="$FIXES"

	if [ -n "$CMD" ] && [ -d "/sys/devices/virtual/net/gem-omci" ]; then
		HASH=$(pon_hash)
		if [ "$HASH" != "$LAST_HASH" ]; then
			if VLANS=$(flock /tmp/8311-fix-vlans.lock -c "$CMD" 2>&1); then
				LAST_HASH="$HASH"
				echo "8311 VLANs daemon: new configuration detected, ran fix-vlans script:" | to_console
				echo "$VLANS" | to_console
			fi
		fi
	fi

	sleep 5
done
