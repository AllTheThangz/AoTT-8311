#!/bin/sh /etc/rc.common

_lib_8311 2>/dev/null || . /lib/8311.sh

START=18

start() {
	CONSOLE_EN=$(get_8311_console_en)
	DYING_GASP_EN=$(get_8311_dying_gasp_en)

	if [ "$CONSOLE_EN" != "1" ]; then
		echo "Disabling serial console output, set fwenv 8311_console_en to 1 to re-enable" | to_console
		UART_TX="low"
	else
		UART_TX="high"
	fi

	if [ "$DYING_GASP_EN" = "1" ]; then
		echo "Enabling dying gasp. This will disable serial console input, set fwenv 8311_dying_gasp_en to 0 to re-enable" | to_console
		UART_RX="low"
	else
		UART_RX="high"
	fi

	# Delay to give enough time to write to console if UART TX is being disabled
	[ "$UART_TX" = "low" ] && sleep 1

	[ -e "/sys/class/gpio/gpio508" ] || echo 508 > "/sys/class/gpio/export"
	echo "$UART_RX" > "/sys/class/gpio/gpio508/direction"

	[ -e "/sys/class/gpio/gpio510" ] || echo 510 > "/sys/class/gpio/export"
	echo "$UART_TX" > "/sys/class/gpio/gpio510/direction"

	# Move cursor to begining of line to hide garbage created by setting UART_TX
	[ "$UART_TX" = "high" ] && echo -n -e "\r" | to_console


	# Custom hostname suppport
	SYS_HOSTNAME=$(get_8311_hostname)
	[ -n "$SYS_HOSTNAME" ] && set_8311_hostname "$SYS_HOSTNAME"

	# LuCI i18n support
	SYS_LANG=$(get_8311_lang)
	[ -n "$SYS_LANG" ] && set_8311_lang "$SYS_LANG"

	# Apply an existing, validated saved administrator hash. Never generate a
	# shared password, log the value, or replace it with an unknown default.
	ROOT_PWHASH=$(get_8311_root_pwhash)
	if [ -n "$ROOT_PWHASH" ]; then
		if ! set_8311_root_pwhash "$ROOT_PWHASH"; then
			unset ROOT_PWHASH
			echo "Security: failed to apply saved root credential at boot" | to_console
			return 1
		fi
		# Read back the live shadow field without passing secret material on the
		# awk command line or emitting the comparison values to logs/stdout.
		if ! { printf '%s\n' "$ROOT_PWHASH"; cat /etc/shadow; } | awk -F: '
			NR == 1 { expected=$0; next }
			$1 == "root" { found=1; if ($2 != expected) exit 1 }
			END { if (!found) exit 1 }
		' >/dev/null 2>&1; then
			unset ROOT_PWHASH
			echo "Security: saved root credential did not survive live readback" | to_console
			return 1
		fi
		unset ROOT_PWHASH
	else
		# A blank root field is not a safe deployment default. Report only
		# the state; credential creation requires local administrative action.
		if awk -F: '$1 == "root" && $2 == "" { blank=1 } END { exit !blank }' /etc/shadow; then
			echo "Security warning: no valid saved root credential; configure a unique password and restrict management access" | to_console
		fi
	fi
}

boot() {
	# 8311 MOD: Remove persistent root
	_8311_check_persistent_root || return 1

	# 8311 MOD: persistent server and client key
	DROPBEAR_RSA_KEY=$(uci -qc /ptconf/8311 get dropbear.rsa_key.value)
	DROPBEAR_PUBKEY=$(uci -qc /ptconf/8311 get dropbear.public_key.value)
	DROPBEAR_PUBKEY_BASE64=$(uci -qc /ptconf/8311 get dropbear.public_key.encryflag)

	[ -f "/ptconf/8311/dropbear" ] && rm -fv "/ptconf/8311/dropbear"
	mkdir -p /ptconf/8311 /ptconf/8311/dropbear /ptconf/8311/uhttpd /ptconf/8311/.ssh
	chmod 700 /ptconf/8311/dropbear /ptconf/8311/uhttpd /ptconf/8311/.ssh
	ln -fsv /ptconf/8311/.ssh/authorized_keys /ptconf/8311/dropbear/authorized_keys

	if [ -n "$DROPBEAR_RSA_KEY" ]; then
		echo "Migrating dropbear.rsa_key to /ptconf/8311/dropbear/dropbear_rsa_host_key" | tee -a /dev/console

		echo "$DROPBEAR_RSA_KEY" | base64 -d > /ptconf/8311/dropbear/dropbear_rsa_host_key
		chmod 600 /ptconf/8311/dropbear/dropbear_rsa_host_key
	fi

	if [ -n "$DROPBEAR_PUBKEY" ]; then
		echo "Migrating dropbear.public_key to /ptconf/8311/.ssh/authorized_keys" | tee -a /dev/console

		if [ "$DROPBEAR_PUBKEY_BASE64" = "1" ]; then
			echo "$DROPBEAR_PUBKEY" | base64 -d > /ptconf/8311/.ssh/authorized_keys
		else
			echo "$DROPBEAR_PUBKEY" > /ptconf/8311/.ssh/authorized_keys
		fi

		chmod 600 /ptconf/8311/.ssh/authorized_keys
	fi

	start "$@"

}
