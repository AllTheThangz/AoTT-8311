#!/bin/sh

_lib_8311 2>/dev/null || . /lib/8311.sh

# Avoid filling the small in-memory syslog with identical ping messages.
LOGGED_HOST=
while true ; do
	PINGD_ENABLED=$(fwenv_get_8311 "pingd" "1")
	# Ping host to help management work
	PING_HOST=$(get_8311_ping_host)

	if [ "$PINGD_ENABLED" -ne "0" ] 2>/dev/null; then
		if [ "$PING_HOST" != "$LOGGED_HOST" ]; then
			echo "Starting ping to: $PING_HOST" | to_console
			LOGGED_HOST="$PING_HOST"
		fi
		ping -i 5 "$PING_HOST" > /dev/null 2>&1 < /dev/null
		sleep 5
	else
		LOGGED_HOST=
		sleep 30
	fi
done
