#!/bin/sh
# Explicit bank operations. A trial is one boot, not an automatic timeout.
umask 077
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1
MAINT_LIBDIR=${MAINT8311_LIBDIR:-"$SCRIPT_DIR/../../lib"}
MAINT_BINDIR=${MAINT8311_BINDIR:-"$SCRIPT_DIR"}
export MAINT8311_LIBDIR="$MAINT_LIBDIR" MAINT8311_BINDIR="$MAINT_BINDIR"
. "$MAINT_LIBDIR/8311-upgrade-lib.sh" || exit 1
. "$MAINT_LIBDIR/8311-env-lock.sh" || exit 1
COMMAND=${1-}; [ "$#" -gt 0 ] && shift
TARGET= EXPECT_BANK= EXPECT_VERSION= EXPECT_OMCID= BACKUP=
case "$COMMAND" in
	trial|check-json) [ "$#" -eq 1 ] || exit 2; case "$1" in A|B) TARGET=$1 ;; *) exit 2 ;; esac ;;
	status|check|commit|reboot|rollback|cancel-trial) [ "$#" -eq 0 ] || exit 2 ;;
	backup-current|commit-current)
		while [ "$#" -gt 0 ]; do
			[ "$#" -ge 2 ] || exit 2
			case "$1" in
				--expect-bank) [ -z "$EXPECT_BANK" ] || exit 2; EXPECT_BANK=$2 ;;
				--expect-version) [ -z "$EXPECT_VERSION" ] || exit 2; EXPECT_VERSION=$2 ;;
				--expect-omcid) [ -z "$EXPECT_OMCID" ] || exit 2; EXPECT_OMCID=$2 ;;
				--backup-dir) [ -z "$BACKUP" ] || exit 2; BACKUP=$2 ;;
				*) exit 2 ;;
			esac
			shift 2
		done
		case "$BACKUP" in /*) ;; *) fail "Backup directory must be a new absolute path." ;; esac
		if [ "$COMMAND" = commit-current ]; then
			case "$EXPECT_BANK" in A|B) ;; *) fail "An expected running bank is required." ;; esac
			[ -n "$EXPECT_VERSION" ] && [ "${#EXPECT_VERSION}" -le 100 ] && [ "${#EXPECT_OMCID}" -eq 64 ] || fail "Exact firmware version and OMCI SHA256 are required."
			case "$EXPECT_OMCID" in *[!0-9a-f]*) fail "Invalid expected OMCI hash." ;; esac
		fi
		;;
	*) printf 'Usage: %s status|check|check-json BANK|trial BANK|cancel-trial|commit|reboot|rollback|backup-current --backup-dir NEW_DIR|commit-current --expect-bank BANK --expect-version VERSION --expect-omcid SHA256 --backup-dir NEW_DIR\n' "$0" >&2; exit 2 ;;
esac
lock_upgrade
lock_environment || fail "Another environment/configuration operation is in progress."
WORKDIR=$(mktemp -d /tmp/8311-bankctl.XXXXXX) || exit 1
trap 'rm -rf "$WORKDIR"' 0
trap 'exit 1' HUP INT TERM
load_environment && check_boot_contract || fail "Cannot establish a compatible boot environment."

check_identity() {
	local version hash
	[ "$ACTIVE" = "$EXPECT_BANK" ] || fail "Running bank differs from the expected bank."
	# Read text, never source firmware metadata.
	version=$(awk -F= '$1 == "FW_LONG_VERSION" {n++; value=substr($0,17)} END {if(n != 1) exit 1; print value}' /etc/8311_version) || fail "Cannot read running firmware identity."
	[ "$version" = "$EXPECT_VERSION" ] || fail "Running firmware version differs from the expected version."
	hash=$(sha_file /usr/bin/omcid) || fail "Cannot hash running OMCI executable."
	[ "$hash" = "$EXPECT_OMCID" ] || fail "Running OMCI differs from the expected executable."
}

backup_current() {
	local part info device capacity expected actual total=0
	[ ! -e "$BACKUP" ] && [ ! -L "$BACKUP" ] || fail "Backup directory already exists; choose a new path."
	: > "$WORKDIR/backup-plan" || exit 1
	for part in kernel bootcore rootfs; do
		info=$(volume_info "$part$ACTIVE" 96) || fail "Cannot plan active-bank backup."
		capacity=${info#*:}; total=$((total + capacity))
		printf '%s %s %s\n' "$part" "${info%%:*}" "$capacity" >> "$WORKDIR/backup-plan" || exit 1
	done
	require_tmp_space "$total" || fail "Insufficient memory/space for the active-bank backup."
	mkdir -m 700 "$BACKUP" || fail "Cannot create private backup directory."
	# A partial backup deliberately has no COMPLETE marker.
	cp "$WORKDIR/environment" "$BACKUP/boot-environment.txt" &&
		cp /proc/cmdline "$BACKUP/cmdline.txt" && cp /proc/mtd "$BACKUP/mtd.txt" &&
		cp /etc/8311_version "$BACKUP/8311_version.txt" || fail "Cannot back up bank metadata."
	printf 'bank=%s\nformat=full-volume-capacity\n' "$ACTIVE" > "$BACKUP/metadata.txt" || exit 1
	: > "$BACKUP/SHA256SUMS" || exit 1
	while read -r part id capacity; do
		device=/dev/ubi0_$id
		capture "$BACKUP/$part$ACTIVE.ubi" "$capacity" 60 head -c "$capacity" "$device" || fail "Active-bank backup failed: $part."
		[ "$(wc -c < "$BACKUP/$part$ACTIVE.ubi")" -eq "$capacity" ] || fail "Short active-bank backup: $part."
		expected=$(sha_file "$BACKUP/$part$ACTIVE.ubi") || fail "Cannot hash backup."
		actual=$(checked_stream_sha "$capacity" "$device") || fail "Cannot independently verify source backup bytes."
		[ "$expected" = "$actual" ] || fail "Active bank changed or backup bytes differ."
		printf '%s  %s%s.ubi\n' "$expected" "$part" "$ACTIVE" >> "$BACKUP/SHA256SUMS" || exit 1
	done < "$WORKDIR/backup-plan"
	for part in boot-environment.txt cmdline.txt mtd.txt 8311_version.txt metadata.txt; do
		expected=$(sha_file "$BACKUP/$part") || fail "Cannot hash backup metadata."
		printf '%s  %s\n' "$expected" "$part" >> "$BACKUP/SHA256SUMS" || exit 1
	done
	printf 'Verified full active-bank backup; retain this off-device before reboot.\n' > "$BACKUP/COMPLETE" || exit 1
	sync || fail "Could not sync the active-bank backup."
	printf 'Verified backup: %s\n' "$BACKUP"
}

case "$COMMAND" in
	status)
		print_bank_status || fail "Cannot serialize bank state."
		;;
	check-json)
		if timeout -k 2 90 "$MAINT_BINDIR/8311-bank-check.sh" "$TARGET" >"$WORKDIR/check-output" 2>&1 8>&- 9>&-; then
			printf '{"schema":1,"bank":"%s","verified":true}\n' "$TARGET"
		else
			printf '{"schema":1,"bank":"%s","verified":false}\n' "$TARGET"
			exit 1
		fi
		;;
	cancel-trial)
		if [ -n "$ACTIVATE" ]; then
			# Cancellation restores the checked committed path and never reboots.
			check_bank "$COMMITTED"
			clear_activation || fail "Could not clear both pending-trial copies; recheck state before reboot."
			printf 'Pending trial cancelled; bank %s remains committed. No reboot requested.\n' "$COMMITTED"
		else
			printf 'No pending trial; boot selection is unchanged.\n'
		fi
		;;
	check)
		printf 'Running=%s Committed=%s One-shot=%s\n' "$ACTIVE" "$COMMITTED" "${ACTIVATE:-none}"
		check_bank "$ACTIVE"
		;;
	backup-current)
		[ -z "$ACTIVATE" ] || fail "A one-shot activation is pending."
		check_bank "$ACTIVE"
		backup_current
		;;
	commit-current)
		[ -z "$ACTIVATE" ] || fail "Boot or cancel the pending activation before reconciliation."
		check_identity
		check_bank "$ACTIVE"
		backup_current
		# Reconfirm the exact live identity and boot state after backup reads.
		load_environment && check_boot_contract || fail "Boot environment changed during backup."
		[ -z "$ACTIVATE" ] || fail "Boot activation changed during backup."
		check_identity
		set_environment commit_bank "$ACTIVE" || fail "Could not save both committed-bank copies; recheck state before continuing."
		printf 'Current verified bank %s is committed.\n' "$ACTIVE"
		;;
	trial)
		[ "$ACTIVE" = "$COMMITTED" ] && [ "$TARGET" != "$ACTIVE" ] && [ -z "$ACTIVATE" ] || fail "Confirm/leave the current trial or cancel pending activation first."
		check_bank "$ACTIVE"
		check_bank "$TARGET"
		set_environment img_activate "$TARGET" || fail "Could not save both one-shot copies; recheck state before reboot."
		printf 'Bank %s selected for one boot; bank %s remains committed. Run bankctl reboot explicitly.\n' "$TARGET" "$COMMITTED"
		;;
	commit)
		[ -z "$ACTIVATE" ] || fail "Boot the selected trial before confirming it."
		check_bank "$ACTIVE"
		[ "$ACTIVE" = "$COMMITTED" ] || set_environment commit_bank "$ACTIVE" || fail "Could not confirm both committed-bank copies."
		printf 'Current bank %s is committed.\n' "$ACTIVE"
		;;
	rollback|reboot)
		if [ "$COMMAND" = rollback ]; then TARGET=$COMMITTED; else TARGET=${ACTIVATE:-$COMMITTED}; fi
		check_bank "$TARGET"
		if [ "$COMMAND" = rollback ] && [ -n "$ACTIVATE" ]; then clear_activation || fail "Could not clear both one-shot copies; recheck state before reboot."; fi
		sync || fail "Could not sync before reboot."
		reboot || fail "Reboot request failed."
		printf 'Reboot requested into bank %s.\n' "$TARGET"
		;;
esac
