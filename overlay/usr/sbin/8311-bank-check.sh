#!/bin/sh
# Read-only content verification. Mutating callers hold both shared locks.
umask 077
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1
MAINT_LIBDIR=${MAINT8311_LIBDIR:-"$SCRIPT_DIR/../../lib"}
MAINT_BINDIR=${MAINT8311_BINDIR:-"$SCRIPT_DIR"}
MAINT_LIBEXEC=${MAINT8311_LIBEXECDIR:-"$SCRIPT_DIR/../libexec"}
. "$MAINT_LIBDIR/8311-upgrade-lib.sh" || exit 1
[ "$#" -eq 1 ] || exit 2
case "$1" in A|B) BANK=$1 ;; *) exit 2 ;; esac
WORKDIR=$(mktemp -d /tmp/8311-bankcheck.XXXXXX) || exit 1
trap 'rm -rf "$WORKDIR"' 0
trap 'exit 1' HUP INT TERM
capture "$WORKDIR/environment" 65536 5 fw_printenv || fail "Cannot read bank validity."
[ "$(env_value "img_valid$BANK")" = true ] || fail "Bank $BANK is not marked complete."
bank_manifest "$BANK" || fail "Bank $BANK has no complete supported receipt."
while read -r PART SIZE HASH; do
	INFO=$(volume_info "$PART$BANK" "$SIZE") || fail "Cannot resolve $PART$BANK."
	DEVICE=/dev/ubi0_${INFO%%:*}
	check_header "$DEVICE" "$PART" "${INFO#*:}" bank || fail "Invalid $PART$BANK header."
	ACTUAL=$(checked_stream_sha "$SIZE" "$DEVICE") || fail "Cannot read $PART$BANK."
	HASH=$(printf '%s' "$HASH" | tr A-F a-f) || exit 1
	[ "$ACTUAL" = "$HASH" ] || fail "Bank $BANK $PART bytes differ from the supported manifest."
	check_component_profile "$PART" "$SIZE" "$HASH" || fail "Bank $BANK $PART is incompatible with this release profile."
done < "$WORKDIR/manifest"
qualify_rootfs "$BANK" common || fail "Bank $BANK failed read-only rootfs qualification."
printf 'Bank %s verified against its complete manifest and required runtime profile.\n' "$BANK"
