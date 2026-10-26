#!/bin/sh
# Maint3 installer: validate private staged bytes, plan named inactive volumes,
# write and read back each, then change boot selection. No volume resizing.
umask 077
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1
MAINT_LIBDIR=${MAINT8311_LIBDIR:-"$SCRIPT_DIR/../../lib"}
MAINT_BINDIR=${MAINT8311_BINDIR:-"$SCRIPT_DIR"}
MAINT_LIBEXEC=${MAINT8311_LIBEXECDIR:-"$SCRIPT_DIR/../libexec"}
export MAINT8311_LIBDIR="$MAINT_LIBDIR" MAINT8311_BINDIR="$MAINT_BINDIR"
. "$MAINT_LIBDIR/8311-upgrade-lib.sh" || exit 1
. "$MAINT_LIBDIR/8311-env-lock.sh" || exit 1
usage() {
	printf 'Usage: %s [--validate] [--install] [--yes] [--trial|--no-commit] [--reboot] FILE\n' "$0"
	printf '%s\n' 'With no mode, validates and installs. Default install stages a qualified bank without changing boot selection.' \
		'--trial selects one boot without changing the committed bank.' \
		'--no-commit is a compatibility alias for the default stage-only behavior.' \
		'Reboot is never automatic unless --reboot is given.'
}
INSTALL=false VALIDATE=false YES=false TRIAL=false NO_COMMIT=true REBOOT=false TAR=
while [ "$#" -gt 0 ]; do
	case "$1" in
		-h|--help) usage; exit 0 ;;
		-v|--validate) VALIDATE=true ;;
		-i|--install) INSTALL=true ;;
		-y|--yes) YES=true ;;
		-r|--reboot) REBOOT=true ;;
		--trial) TRIAL=true; NO_COMMIT=true ;;
		--no-commit) NO_COMMIT=true ;;
		--) [ "$#" -eq 2 ] && [ -z "$TAR" ] || exit 2; TAR=$2; break ;;
		-*) usage >&2; exit 2 ;;
		*) [ -z "$TAR" ] || exit 2; TAR=$1 ;;
	esac
	shift
done
if ! $INSTALL && ! $VALIDATE; then INSTALL=true; fi
if $REBOOT && { ! $INSTALL || ! $TRIAL; }; then fail "--reboot requires an install that selects the new bank."; fi
[ -n "$TAR" ] && [ -f "$TAR" ] && [ ! -L "$TAR" ] && [ -r "$TAR" ] || fail "Upgrade must be a readable regular file."
lock_upgrade
lock_environment || fail "Another environment/configuration operation is in progress."
WORKDIR=$(mktemp -d /tmp/8311-upgrade.XXXXXX) || fail "Cannot create private staging directory."
trap 'rm -rf "$WORKDIR"' 0
trap 'exit 1' HUP INT TERM
ARCHIVE_SIZE=$(wc -c < "$TAR") || fail "Cannot size archive."
case "$ARCHIVE_SIZE" in ''|*[!0-9]*) fail "Invalid archive size." ;; esac
[ "${#ARCHIVE_SIZE}" -le 9 ] && [ "$ARCHIVE_SIZE" -ge 1024 ] && [ "$ARCHIVE_SIZE" -le 134217728 ] || fail "Archive outside 1 KiB–128 MiB limit."
# At most the archive's byte count is staged. Zero-total tmpfs accounting falls
# back to available RAM; every write/close and producer status is also checked.
require_tmp_space "$ARCHIVE_SIZE" || fail "Insufficient staging memory/space."
bounded_run 33554432 90 lua "$MAINT_LIBEXEC/8311-stage-upgrade.lua" "$TAR" "$WORKDIR" "$ARCHIVE_SIZE" || fail "Archive staging failed."
FW_VERSION= FW_REVISION= FW_VARIANT= FW_TARGET= FW_PROFILE=
SIZE_KERNEL= SIZE_BOOTCORE= SIZE_ROOTFS= SHA256_KERNEL= SHA256_BOOTCORE= SHA256_ROOTFS=
SEEN='|'
while IFS= read -r LINE || [ -n "$LINE" ]; do
	[ -n "$LINE" ] || continue
	case "$LINE" in *=*) ;; *) fail "Invalid control field." ;; esac
	KEY=${LINE%%=*}; VALUE=${LINE#*=}
	case "$KEY" in ''|*[!A-Z0-9_]*) fail "Invalid control key." ;; esac
	case "$SEEN" in *"|$KEY|"*) fail "Duplicate control field: $KEY." ;; esac
	SEEN="$SEEN$KEY|"
	case "$KEY" in
		FW_VERSION) FW_VERSION=$VALUE ;; FW_REVISION) FW_REVISION=$VALUE ;;
		FW_VARIANT) FW_VARIANT=$VALUE ;; FW_TARGET) FW_TARGET=$VALUE ;; FW_PROFILE) FW_PROFILE=$VALUE ;;
		SIZE_KERNEL) SIZE_KERNEL=$VALUE ;; SIZE_BOOTCORE) SIZE_BOOTCORE=$VALUE ;; SIZE_ROOTFS) SIZE_ROOTFS=$VALUE ;;
		SHA256_KERNEL) SHA256_KERNEL=$VALUE ;; SHA256_BOOTCORE) SHA256_BOOTCORE=$VALUE ;; SHA256_ROOTFS) SHA256_ROOTFS=$VALUE ;;
		FW_VER|FW_LONG_VERSION|FW_REV|FW_SUFFIX) ;; # Legacy informational aliases.
		*) fail "Unsupported control field: $KEY." ;;
	esac
done < "$WORKDIR/control"
[ -n "$FW_VERSION" ] && [ -n "$FW_REVISION" ] || fail "Missing firmware version information."
case "$FW_VARIANT" in basic) ;; *) fail "Unsupported firmware variant." ;; esac
case "$FW_TARGET" in WAS-110) ;; *) fail "Firmware is for another target." ;; esac
[ "$FW_PROFILE" = potron-prx126-aott-v1 ] || fail "Missing or unsupported compatibility profile."
case "$FW_VERSION:$FW_REVISION" in *[!a-zA-Z0-9._+:~-]*) fail "Invalid firmware version information." ;; esac
[ "${#FW_VERSION}" -le 64 ] && [ "${#FW_REVISION}" -le 64 ] || fail "Firmware version is too long."
for SIZE in "$SIZE_KERNEL" "$SIZE_BOOTCORE" "$SIZE_ROOTFS"; do
	case "$SIZE" in ''|0*|*[!0-9]*) fail "Component sizes must be positive canonical decimals." ;; esac
	[ "${#SIZE}" -le 8 ] || fail "Component size exceeds limit."
done
[ "$SIZE_KERNEL" -le 8388608 ] && [ "$SIZE_BOOTCORE" -le 8388608 ] && [ "$SIZE_ROOTFS" -le 33554432 ] || fail "Component size exceeds limit."
validate_image() {
	local file="$1" name="$2" size="$3" expected="$4" actual crc
	[ "${#expected}" -eq 64 ] || fail "Missing/invalid $name checksum."
	case "$expected" in *[!0-9a-fA-F]*) fail "Invalid $name checksum." ;; esac
	expected=$(printf '%s' "$expected" | tr A-F a-f) || exit 1
	[ "$(wc -c < "$WORKDIR/$file")" -eq "$size" ] || fail "$name size differs from control."
	actual=$(sha_file "$WORKDIR/$file") || fail "Unable to hash $name."
	[ "$actual" = "$expected" ] || fail "$name checksum mismatch."
	check_component_profile "$name" "$size" "$expected" || fail "Incompatible $name for the fixed board/runtime profile."
	check_header "$WORKDIR/$file" "$name" "$size" exact || fail "Invalid $name image header."
	if [ "$name" != rootfs ]; then
		crc=$(stream_digest "$WORKDIR" crc32 "$((size - 64))" timeout -k 1 30 tail -c +65 "$WORKDIR/$file") || fail "Cannot check $name payload."
		[ "$crc" = "$DATA_CRC" ] || fail "$name data CRC mismatch."
	fi
	chmod 400 "$WORKDIR/$file" || fail "Cannot protect staged $name."
	printf 'Validated %s: %s bytes\n' "$name" "$size"
}
validate_image kernel.bin kernel "$SIZE_KERNEL" "$SHA256_KERNEL"
validate_image bootcore.bin bootcore "$SIZE_BOOTCORE" "$SHA256_BOOTCORE"
validate_image rootfs.img rootfs "$SIZE_ROOTFS" "$SHA256_ROOTFS"
printf 'Archive/profile preflight passed: %s %s %s. Rootfs content qualification is required after writing the inactive bank.\n' "$FW_VERSION" "$FW_VARIANT" "$FW_REVISION"
$INSTALL || exit 0
load_environment && check_boot_contract || fail "Cannot establish a compatible boot environment."
[ "$ACTIVE" = "$COMMITTED" ] || fail "Running and committed banks differ; back up and confirm the current bank or return to the committed bank first."
[ -z "$ACTIVATE" ] || fail "A one-shot boot is pending; finish or cancel it before installing."
ACTIVE_VALID=$(env_value "img_valid$ACTIVE") || fail "Missing current-bank validity marker."
[ "$ACTIVE_VALID" = true ] || fail "The current bank is not marked complete."
if [ "$ACTIVE" = A ]; then INSTALL_BANK=B; else INSTALL_BANK=A; fi
# Validate the preserved bank before consuming the other bank as an upgrade slot.
check_bank "$ACTIVE"
KERNEL_INFO=$(volume_info "kernel$INSTALL_BANK" "$SIZE_KERNEL") || fail "Kernel does not fit its existing inactive volume."
BOOTCORE_INFO=$(volume_info "bootcore$INSTALL_BANK" "$SIZE_BOOTCORE") || fail "Bootcore does not fit its existing inactive volume."
ROOTFS_INFO=$(volume_info "rootfs$INSTALL_BANK" "$SIZE_ROOTFS") || fail "RootFS does not fit its existing inactive volume."
KERNEL_UBI=/dev/ubi0_${KERNEL_INFO%%:*}
BOOTCORE_UBI=/dev/ubi0_${BOOTCORE_INFO%%:*}
ROOTFS_UBI=/dev/ubi0_${ROOTFS_INFO%%:*}
[ "$KERNEL_UBI" != "$BOOTCORE_UBI" ] && [ "$KERNEL_UBI" != "$ROOTFS_UBI" ] && [ "$BOOTCORE_UBI" != "$ROOTFS_UBI" ] || fail "Target volumes alias each other."
for PART in kernel bootcore rootfs; do
	INFO=$(volume_info "$PART$ACTIVE" 96) || fail "Cannot resolve preserved-bank volumes."
	DEVICE=/dev/ubi0_${INFO%%:*}
	[ "$DEVICE" != "$KERNEL_UBI" ] && [ "$DEVICE" != "$BOOTCORE_UBI" ] && [ "$DEVICE" != "$ROOTFS_UBI" ] || fail "Target aliases the running bank."
done
printf 'Preserving bank %s; installing bank %s.\n' "$ACTIVE" "$INSTALL_BANK"
if ! $YES; then
	printf 'Install these preflight-checked bytes into the inactive bank? (y/N) '
	IFS= read -r ANSWER || exit 2
	case "$ANSWER" in y|Y|yes|YES) ;; *) exit 2 ;; esac
fi
# Recheck boot state under the same lock immediately before the first mutation.
OLD_ACTIVE=$ACTIVE
load_environment && check_boot_contract || fail "Boot environment changed or became unreadable."
[ "$ACTIVE" = "$OLD_ACTIVE" ] && [ "$COMMITTED" = "$ACTIVE" ] && [ -z "$ACTIVATE" ] || fail "Boot selection changed before installation."
persist_receipt "$INSTALL_BANK" incomplete || fail "Cannot persist the incomplete-bank receipt."
set_environment "img_valid$INSTALL_BANK" false || fail "Cannot mark target incomplete."
rm -f /tmp/8311-alt-firmware
install_image() {
	local file="$1" size="$2" expected="$3" device="$4" actual
	expected=$(printf '%s' "$expected" | tr A-F a-f) || exit 1
	printf 'Writing %s to %s...\n' "$file" "$device"
	# Do not kill a flash update mid-write with an arbitrary timeout.
	ubiupdatevol -s "$size" "$device" - < "$WORKDIR/$file" || fail "Write failed: $file; inactive bank remains incomplete."
	actual=$(checked_stream_sha "$size" "$device") || fail "Readback failed: $file; inactive bank remains incomplete."
	[ "$actual" = "$expected" ] || fail "Readback mismatch: $file; inactive bank remains incomplete."
}
install_image kernel.bin "$SIZE_KERNEL" "$SHA256_KERNEL" "$KERNEL_UBI"
install_image bootcore.bin "$SIZE_BOOTCORE" "$SHA256_BOOTCORE" "$BOOTCORE_UBI"
install_image rootfs.img "$SIZE_ROOTFS" "$SHA256_ROOTFS" "$ROOTFS_UBI"
# Keep the incomplete receipt and img_valid=false throughout qualification.
# Neither a passing header nor matching flash hash establishes mountability.
qualify_rootfs "$INSTALL_BANK" candidate || fail "Written rootfs failed boot/runtime qualification; target remains incomplete and selectors are unchanged."
persist_receipt "$INSTALL_BANK" complete || fail "Cannot persist the verified-bank receipt."
set_environment "img_valid$INSTALL_BANK" true || fail "Cannot mark installed bank complete."
if $TRIAL; then
	set_environment img_activate "$INSTALL_BANK" || fail "Images verified, but one-shot selection failed. Recheck bank state before rebooting."
	printf 'Bank %s is ready for one boot; bank %s remains committed.\n' "$INSTALL_BANK" "$ACTIVE"
else
	printf 'Bank %s is complete; boot selection is unchanged.\n' "$INSTALL_BANK"
fi
if $REBOOT; then
	# Release this process's lock, then let bankctl reacquire and check next boot.
	unlock_environment || fail "Cannot release environment lock."
	flock -u 9 || fail "Cannot release upgrade lock."
	"$MAINT_BINDIR/8311-bankctl.sh" reboot || fail "Install completed but reboot request failed."
fi
exit 0
