#!/bin/sh
# Staging/stream primitives adapted from linlunaire/8311-was-110-firmware-builder
# cec7b76ef3ca8b3ba73c112893b0dbb215c5e055. Boot/volume guards and qualified release profile below are maint3.
fail() { printf '%s\n' "$1" >&2; exit 1; }
# Bound query/extraction output without hiding the command's exit status.
# BusyBox ash and dash use 512-byte blocks; bash uses 1024-byte blocks.
bounded_exec() {
	local bytes="$1" unit=512
	shift
	[ -z "${BASH_VERSION:-}" ] || unit=1024
	( ulimit -c 0 || exit 126
	  ulimit -f "$(( (bytes + unit - 1) / unit ))" || exit 126
	  # BusyBox timeout watchdogs may outlive their producer briefly. The
	  # controlling operation owns the lock; read-only workers must not retain it.
	  exec 8>&- 9>&-
	  exec "$@" )
}

bounded_run() {
	local bytes="$1" seconds="$2"
	shift 2
	bounded_exec "$bytes" timeout -k 1 "$seconds" "$@"
}

capture_result() {
	local file="$1" bytes="$2" code="$3"
	local size
	size=$(wc -c < "$file") || return 1
	if [ "$size" -gt "$bytes" ] || { [ "$code" -ne 0 ] && [ "$size" -ge "$bytes" ]; }; then
		echo "Output limit exceeded: ${file##*/}; incomplete output discarded." >&2
		rm -f "$file"; return 3
	fi
	case "$code" in
		0) return 0 ;;
		124|137|143) echo "Query timed out or was terminated: ${file##*/}; incomplete output discarded." >&2 ;;
		*) echo "Query failed ($code): ${file##*/}; incomplete output discarded." >&2 ;;
	esac
	rm -f "$file"
	return "$code"
}

capture() {
	local file="$1" bytes="$2" seconds="$3" code=0
	shift 3
	bounded_run "$bytes" "$seconds" "$@" > "$file" 2>/dev/null || code=$?
	capture_result "$file" "$bytes" "$code"
}

# The caller supplies timeout and its grace period. Both output streams and
# regular files written by descendants inherit the same per-file size limit.
capture_combined() {
	local file="$1" bytes="$2" code=0
	shift 2
	bounded_exec "$bytes" "$@" > "$file" 2>&1 || code=$?
	capture_result "$file" "$bytes" "$code"
}

# Hash and count the same byte stream. Keep every producer/consumer status;
# only tiny result files are staged, never a complete component payload.
stream_digest() (
	local directory="$1" algorithm="$2" expected="$3" work code=0
	local reader= hasher= counter= copier= size
	shift 3
	work=$(mktemp -d "$directory/digest.XXXXXX") || exit 1
	cleanup_stream() {
		local child
		# These private read-only workers may still be blocked opening a FIFO.
		for child in "$copier" "$reader" "$hasher" "$counter"; do
			[ -z "$child" ] || kill -KILL "$child" 2>/dev/null || true
		done
		wait 2>/dev/null || true
		rm -rf "$work"
	}
	trap cleanup_stream 0
	trap 'exit 1' HUP INT TERM
	mkfifo "$work/input" "$work/hash" "$work/count" || exit 1
	"$algorithm" < "$work/hash" > "$work/value" 8>&- 9>&- &
	hasher=$!
	wc -c < "$work/count" > "$work/size" 8>&- 9>&- &
	counter=$!
	"$@" > "$work/input" 8>&- 9>&- &
	reader=$!
	tee "$work/hash" < "$work/input" > "$work/count" 8>&- 9>&- &
	copier=$!
	# wait is interruptible by our traps; a failed copier may not have opened
	# every FIFO, so cancel its peers before waiting for their completion.
	wait "$copier" || { copier=; exit 1; }; copier=
	wait "$reader" || code=1; reader=
	wait "$hasher" || code=1; hasher=
	wait "$counter" || code=1; counter=
	[ "$code" -eq 0 ] || exit 1
	IFS= read -r size < "$work/size" || exit 1
	[ "$size" -eq "$expected" ] || exit 1
	cat "$work/value"
)

# /tmp on the target reports zero filesystem blocks: also budget available RAM.
require_tmp_space() {
	case "${1-}" in ''|*[!0-9]*) return 2 ;; esac
	case "$1" in 0?*) return 2 ;; esac
	[ "$#" -eq 1 ] && [ "${#1}" -le 9 ] || return 2
	local MEM DISK TOTAL
	MEM=$(awk '
		/^MemAvailable:/ { available=$2; found=1 }
		/^MemFree:/ { free=$2 }
		/^Buffers:/ { buffers=$2 }
		/^Cached:/ { cached=$2 }
		/^Shmem:/ { shared=$2 }
		END { print int(found ? available : free+buffers+cached-shared) }
	' /proc/meminfo) || return 1
	DISK=$(df -Pk /tmp/ 2>/dev/null) || return 1
	DISK=$(printf '%s\n' "$DISK" | awk 'NR==2 {print $2 ":" $4}') || return 1
	case "$MEM:$DISK" in *[!0-9:]*|:*|*:|*::*|*:*:*:*) return 1 ;; esac
	TOTAL=${DISK%:*}
	DISK=${DISK#*:}
	[ "$DISK" -le "$TOTAL" ] || return 1
	# Only zero total capacity means unavailable accounting; zero free can mean full.
	[ "$TOTAL" -eq 0 ] || [ "$MEM" -le "$DISK" ] || MEM=$DISK
	# Leave 8 MiB for management/driver processes. Writes still check ENOSPC.
	[ "$MEM" -ge "$(( ($1 + 1023) / 1024 + 8192 ))" ] || {
		echo 'Insufficient temporary space or available memory.' >&2
		return 1
	}
}

sha_file() {
	local output hash
	output=$(sha256sum "$1" 8>&- 9>&-) || return 1
	hash=${output%% *}
	[ "${#hash}" -eq 64 ] || return 1
	case "$hash" in *[!0-9a-f]*) return 1 ;; esac
	[ "$output" = "$hash  $1" ] || [ "$output" = "$hash *$1" ] || return 1
	printf '%s\n' "$hash"
}

active_bank() {
	awk '{for(i=1;i<=NF;i++) if($i ~ /^rootfsname=/) {n++; bank=$i}}
		END {if(n != 1 || bank !~ /^rootfsname=rootfs[AB]$/) exit 1; print substr(bank,length(bank),1)}' /proc/cmdline
}

env_value() {
	awk -F= -v key="$1" '$1 == key {n++; value=substr($0,length(key)+2)}
		END {if(n == 1) print value; else if(n == 0) exit 2; else exit 1}' "$WORKDIR/environment"
}

load_environment() {
	capture "$WORKDIR/environment" 65536 5 fw_printenv || return 1
	ACTIVE=$(active_bank) || return 1
	local saved
	saved=$(env_value active_bank) || return 1
	[ "$saved" = "$ACTIVE" ] || return 1
	COMMITTED=$(env_value commit_bank) || return 1
	case "$COMMITTED" in A|B) ;; *) return 1 ;; esac
	ACTIVATE=$(env_value img_activate) || { [ "$?" -eq 2 ] || return 1; ACTIVATE=; }
	case "$ACTIVATE" in ''|A|B) ;; *) return 1 ;; esac
}

# Pin the bootloader operations that make one-shot activation meaningful. Hashes
# cover exact fw_printenv key=value lines, including a final newline; never eval.
check_boot_contract() {
	local key expected value actual
	while read -r key expected; do
		value=$(env_value "$key") || return 1
		printf '%s=%s\n' "$key" "$value" > "$WORKDIR/env-line" || return 1
		actual=$(sha_file "$WORKDIR/env-line") || return 1
		[ "$actual" = "$expected" ] || { printf 'Unsupported bootloader definition: %s\n' "$key" >&2; return 1; }
	done <<'BOOT_CONTRACT'
bootcmd c79835c0127f4818a7169bd194894a3c213e5807e8344807834721f871905367
flash_flash fbae32411b6547d83727920558a84804d788f22b58a98e092724caff71581afb
select_image 032038a71760be32e195c4ee98e031738436df1dc3a198abb21f3b3d6fa95344
switchbankA 377d142070d135b97d23741d7b8f39801035b5b3a0b6c23332d8ab114f36a9f4
switchbankB d485eb97a891542e78dddb906de75addf02e6c9670e79971108f9b8ce400c719
run_bootcore 26bc8f7585dad3057a15105471c51eadc8458ca4ec2881e7eef7b86bbdf281f9
ubi_init 73eb9d3690db1a33ac6d005bb6320b6e9deefb9cb9bc675fe450628990b35df4
BOOT_CONTRACT
}

set_environment() {
	local key="$1" value="$2" i actual
	case "$key" in commit_bank|img_activate) case "$value" in A|B) ;; *) return 1 ;; esac ;;
		img_validA|img_validB) case "$value" in true|false) ;; *) return 1 ;; esac ;;
		*) return 1 ;;
	esac
	# Stock redundant-env tools require both writes. Any error is failure even
	# though one copy may already have changed; never claim an atomic transaction.
	for i in 1 2; do fw_setenv "$key" "$value" || return 1; done
	capture "$WORKDIR/environment" 65536 5 fw_printenv || return 1
	actual=$(env_value "$key") || return 1
	[ "$actual" = "$value" ]
}

clear_activation() {
	local i value code
	for i in 1 2; do fw_setenv img_activate || return 1; done
	capture "$WORKDIR/environment" 65536 5 fw_printenv || return 1
	code=0; value=$(env_value img_activate) || code=$?
	[ "$code" -eq 2 ] || { [ "$code" -eq 0 ] && [ -z "$value" ]; }
}

# Return ID:capacity only for one exact, existing, healthy named UBI volume.
volume_info() {
	local name="$1" minimum="$2" info id capacity found state type
	info=$(timeout -k 1 5 ubinfo /dev/ubi0 -N "$name" 2>/dev/null 8>&- 9>&-) || return 1
	id=$(printf '%s\n' "$info" | awk '/^Volume ID:/ {print $3}') || return 1
	capacity=$(printf '%s\n' "$info" | tr '(),' '   ' | awk '/^Size:/ {print $4}') || return 1
	found=$(printf '%s\n' "$info" | awk '/^Name:/ {print $2}') || return 1
	state=$(printf '%s\n' "$info" | awk '/^State:/ {print $2}') || return 1
	type=$(printf '%s\n' "$info" | awk '/^Type:/ {print $2}') || return 1
	[ "$found" = "$name" ] && [ "$state" = OK ] && [ "$type" = dynamic ] || return 1
	case "$id:$capacity" in *[!0-9:]*|:*|*:) return 1 ;; esac
	[ "${#id}" -le 3 ] && [ "${#capacity}" -le 9 ] || return 1
	[ "$id" -le 127 ] && [ "$capacity" -ge "$minimum" ] && [ "$capacity" -le 134217728 ] || return 1
	printf '%s:%s\n' "$id" "$capacity"
}

hex_header() {
	local value
	value=$(hexdump -v -s "$1" -n "$2" -e '1/1 "%02x"' "$WORKDIR/header") || return 1
	[ "${#value}" -eq "$((2 * $2))" ] || return 1
	case "$value" in *[!0-9a-f]*) return 1 ;; esac
	printf '%s' "$value"
}

# Header checks return IMAGE_BYTES (including uImage header), DATA_CRC, HEADER_KIND.
# 'exact' requires a uImage to occupy its complete staged file; bank reads allow
# trailing capacity. SquashFS bytes_used always has to fit the declared extent.
check_header() {
	local file="$1" kind="$2" capacity="$3" exact="$4" value expected actual
	capture "$WORKDIR/header" 96 5 head -c 96 "$file" || return 1
	[ "$(wc -c < "$WORKDIR/header")" -eq 96 ] || return 1
	HEADER_KIND=$kind
	if [ "$kind" = rootfs ]; then
		# This bounded parser rejects inconsistent superblocks and table extents.
		# It cannot decode XZ metadata; qualification below reads the mounted tree.
		local checker="${MAINT_LIBEXEC:-$MAINT_BINDIR/../libexec}/8311-squashfs-check.lua"
		IMAGE_BYTES=$(bounded_run 4096 10 lua "$checker" "$file" "$capacity" "$exact") || return 1
		case "$IMAGE_BYTES" in ''|*[!0-9]*) return 1 ;; esac
	else
		[ "$(hex_header 0 4)" = 27051956 ] && [ "$(hex_header 28 3)" = 050502 ] || return 1
		value=$(hex_header 12 4) || return 1
		[ "${value%??????}" = 00 ] || return 1
		IMAGE_BYTES=$((0x$value + 64))
		[ "$IMAGE_BYTES" -gt 64 ] && [ "$IMAGE_BYTES" -le "$capacity" ] || return 1
		[ "$exact" != exact ] || [ "$IMAGE_BYTES" -eq "$capacity" ] || return 1
		expected=$(hex_header 4 4) || return 1
		DATA_CRC=$(hex_header 24 4) || return 1
		capture "$WORKDIR/header.crc" 64 5 head -c 64 "$WORKDIR/header" || return 1
		printf '\000\000\000\000' > "$WORKDIR/zeros" || return 1
		dd if="$WORKDIR/zeros" of="$WORKDIR/header.crc" bs=1 seek=4 conv=notrunc 2>/dev/null || return 1
		actual=$(crc32 < "$WORKDIR/header.crc") || return 1
		[ "$actual" = "$expected" ] || return 1
	fi
}

checked_stream_sha() {
	local result hash
	result=$(stream_digest "$WORKDIR" sha256sum "$1" timeout -k 1 40 head -c "$1" "$2") || return 1
	hash=${result%% *}
	[ "${#hash}" -eq 64 ] || return 1
	case "$hash" in *[!0-9a-f]*) return 1 ;; esac
	[ "$result" = "$hash  -" ] || [ "$result" = "$hash *-" ] || return 1
	printf '%s\n' "$hash"
}

check_bank() {
	timeout -k 2 90 "$MAINT_BINDIR/8311-bank-check.sh" "$1" >/dev/null 8>&- 9>&- ||
		fail "Bank $1 is incomplete, corrupt, or unreadable."
}

lock_upgrade() {
	# Never unlink this pathname: cooperating operations must retain one inode.
	[ ! -L /tmp/8311-firmware-upgrade.lock ] || fail "Unsafe upgrade lock path."
	[ ! -e /tmp/8311-firmware-upgrade.lock ] || [ -f /tmp/8311-firmware-upgrade.lock ] || fail "Upgrade lock is not a regular file."
	exec 9>>/tmp/8311-firmware-upgrade.lock
	flock -n 9 || fail "Another firmware operation is in progress."
}

# /ptconf survives the stock bootcmd that deletes rootfs_data. A separate
# incomplete receipt cannot be repaired accidentally by stock poninit's flag
# refresh. This directory is private to maint2 and contains no ISP credentials.
persist_receipt() {
	local bank="$1" state="$2" directory=/ptconf/8311-maint2 temporary
	case "$bank:$state" in A:incomplete|B:incomplete|A:complete|B:complete) ;; *) return 1 ;; esac
	[ ! -L "$directory" ] || return 1
	if [ ! -d "$directory" ]; then mkdir -m 700 "$directory" || return 1; fi
	[ ! -L "$directory/bank$bank" ] || return 1
	[ ! -e "$directory/bank$bank" ] || [ -f "$directory/bank$bank" ] || return 1
	chmod 700 "$directory" || return 1
	temporary=$(mktemp "$directory/.receipt.XXXXXX") || return 1
	{
		printf 'schema=1\nbank=%s\nstate=%s\n' "$bank" "$state" || return 1
		if [ "$state" = complete ]; then
			printf 'kernel %s %s\nbootcore %s %s\nrootfs %s %s\n' \
				"$SIZE_KERNEL" "$SHA256_KERNEL" "$SIZE_BOOTCORE" "$SHA256_BOOTCORE" "$SIZE_ROOTFS" "$SHA256_ROOTFS" || return 1
		fi
	} > "$temporary" || { rm -f "$temporary"; return 1; }
	chmod 600 "$temporary" && mv -fT "$temporary" "$directory/bank$bank" && sync || { rm -f "$temporary"; return 1; }
}

bank_manifest() {
	local bank="$1" receipt="/ptconf/8311-maint2/bank$1"
	if [ -e "$receipt" ] || [ -L "$receipt" ]; then
		[ -f "$receipt" ] && [ ! -L "$receipt" ] || return 1
		capture "$WORKDIR/receipt" 1024 5 cat "$receipt" || return 1
		# Exactly three canonical entries, in fixed order, without extra fields.
		awk -v bank="$bank" 'NR == 1 {if($0 != "schema=1") exit 1; next}
			NR == 2 {if($0 != "bank=" bank) exit 1; next}
			NR == 3 {if($0 != "state=complete") exit 1; next}
			NR == 4 {if($1 != "kernel" || $2 > 8388608) exit 1}
			NR == 5 {if($1 != "bootcore" || $2 > 8388608) exit 1}
			NR == 6 {if($1 != "rootfs" || $2 > 33554432) exit 1}
			NR > 3 {if(NF != 3 || $2 !~ /^[1-9][0-9]*$/ || length($2)>8 || length($3)!=64 || $3 ~ /[^0-9a-fA-F]/) exit 1; print $0}
			END {if(NR != 6) exit 1}' "$WORKDIR/receipt" > "$WORKDIR/manifest" || return 1
	else
		# The only legacy image qualified for this kit. Different vendor/fork
		# payloads require an explicit independently qualified manifest.
		cat > "$WORKDIR/manifest" <<'STOCK_MANIFEST'
kernel 2274800 d66b24cf873cc1071a3aa2d155bf677f503f10d221513e469083f8a591f6b96c
bootcore 5426656 e99e25332bdcb3c9b0447abad1be9b1e54511b6bda99f2b51ae2499db5b905a4
rootfs 6197248 756da584829d8ef144bdd8e400fb763ff31711e2b84e430912118fb6093b7e33
STOCK_MANIFEST
	fi
}

# A release profile is trusted local policy, never supplied by the uploaded tar.
# Updating the kernel, bootcore or ABI requires a new independently qualified
# profile; the archive cannot grant itself compatibility by claiming a target.
check_component_profile() {
	local part="$1" size="$2" hash="$3" record
	case "$part" in kernel|bootcore) ;; rootfs) return 0 ;; *) return 1 ;; esac
	record=$(awk -v part="$part" '$1 == "component" && $2 == part {n++; if(NF!=4) exit 1; value=$3 " " $4} END {if(n!=1) exit 1; print value}' "$MAINT_LIBDIR/8311-release-profile") || return 1
	hash=$(printf '%s' "$hash" | tr A-F a-f) || return 1
	[ "$record" = "$size $hash" ]
}

# No ancestor may be a symlink: an absolute link inside an untrusted mounted
# tree must never redirect a qualification read into the running rootfs.
profile_path() {
	local root="$1" relative="$2" path="$1" parent part
	case "$relative" in ''|/*|*..*|*[!a-zA-Z0-9_./+-]*) return 1 ;; esac
	parent=${relative%/*}
	local IFS=/
	set -- $parent
	for part do
		path="$path/$part"
		[ -d "$path" ] && [ ! -L "$path" ] || return 1
	done
	printf '%s/%s\n' "$root" "$relative"
}

check_runtime_profile() {
	local root="$1" scope="$2" kind applies relative size expected extra path actual count=0
	while read -r kind applies relative size expected extra; do
		case "$kind" in
			profile|target|variant|component) continue ;;
			file|link) ;;
			*) return 1 ;;
		esac
		case "$applies" in common) ;; candidate) [ "$scope" = candidate ] || continue ;; *) return 1 ;; esac
		path=$(profile_path "$root" "$relative") || return 1
		if [ "$kind" = file ]; then
			[ -z "$extra" ] && [ -f "$path" ] && [ ! -L "$path" ] && [ -r "$path" ] || return 1
			case "$size" in ''|0*|*[!0-9]*) return 1 ;; esac
			[ "${#expected}" -eq 64 ] && [ "$(wc -c < "$path")" -eq "$size" ] || return 1
			actual=$(sha_file "$path") || return 1
			[ "$actual" = "$expected" ] || { printf 'Runtime profile mismatch: %s\n' "$relative" >&2; return 1; }
			# Require execute permission only for paths that are actually invoked as
			# programs/init entry points. Data, configuration, Lua/JS sources and
			# shared objects are integrity-checked above but need not carry +x.
			case "$relative" in
				bin/*|sbin/*|usr/bin/*|usr/sbin/*|usr/libexec/*|etc/init.d/*|etc/preinit)
					[ -x "$path" ] || { printf 'Runtime executable mode mismatch: %s\n' "$relative" >&2; return 1; }
				;;
			esac
		else
			[ -z "$expected$extra" ] && [ -L "$path" ] && [ "$(readlink "$path")" = "$size" ] || return 1
		fi
		count=$((count + 1))
	done < "$MAINT_LIBDIR/8311-release-profile"
	[ "$count" -ge 11 ]
}

# Mount the actual target bank read-only and consume its critical file bytes.
# This does not execute any candidate code and does not consult img_valid or a
# complete receipt, so it can run while a newly written target remains invalid.
qualify_rootfs() (
	local bank="$1" scope="${2:-common}" work root mtd mounted=false
	case "$bank:$scope" in A:common|B:common|A:candidate|B:candidate) ;; *) exit 1 ;; esac
	work=$(mktemp -d "$WORKDIR/qualify.XXXXXX") || exit 1
	root="$work/root"
	cleanup_qualification() {
		if $mounted; then
			umount "$root" 2>/dev/null || { echo "Qualification mount remains at $root; manual cleanup is required." >&2; return 1; }
		fi
		rm -rf "$work"
	}
	trap cleanup_qualification 0
	trap 'exit 1' HUP INT TERM
	mtd=$(awk -v name="\"rootfs$bank\"" '$4==name {n++; value=$1} END {if(n!=1 || value !~ /^mtd[0-9]+:$/) exit 1; sub(":$","",value); sub("^mtd","",value); print value}' /proc/mtd) || exit 1
	mkdir "$root" || exit 1
	mount -t squashfs -o ro "/dev/mtdblock$mtd" "$root" || exit 1
	mounted=true
	check_runtime_profile "$root" "$scope" || { echo "Bank $bank failed required boot/runtime content qualification." >&2; exit 1; }
	umount "$root" || exit 1
	mounted=false
	printf 'Bank %s rootfs mounted read-only and required boot/runtime bytes verified.\n' "$bank"
)

receipt_state() {
	local bank="$1" path="/ptconf/8311-maint2/bank$1"
	if [ ! -e "$path" ] && [ ! -L "$path" ]; then printf missing; return; fi
	[ -f "$path" ] && [ ! -L "$path" ] || { printf invalid; return; }
	if bank_manifest "$bank"; then printf complete; return; fi
	# A canonical incomplete marker is distinguishable from a malformed receipt.
	if [ "$(wc -c < "$path")" -le 128 ] && awk -v bank="$bank" 'NR==1 {if($0!="schema=1") exit 1} NR==2 {if($0!="bank="bank) exit 1} NR==3 {if($0!="state=incomplete") exit 1} END {if(NR!=3) exit 1}' "$path"; then printf incomplete; else printf invalid; fi
}

print_bank_status() {
	local bank state valid part size hash separator
	printf '{"schema":1,"active":"%s","committed":"%s","pending":' "$ACTIVE" "$COMMITTED"
	if [ -n "$ACTIVATE" ]; then printf '"%s"' "$ACTIVATE"; else printf null; fi
	printf ',"boot_contract":true,"running_trial":'
	if [ "$ACTIVE" != "$COMMITTED" ]; then printf true; else printf false; fi
	printf ',"banks":{'
	separator=
	for bank in A B; do
		state=$(receipt_state "$bank") || return 1
		valid=$(env_value "img_valid$bank") || valid=null
		case "$valid" in true|false) ;; *) valid=null ;; esac
		printf '%s"%s":{"valid":%s,"receipt":"%s","components":' "$separator" "$bank" "$valid" "$state"
		if [ "$state" = complete ]; then
			bank_manifest "$bank" || return 1
			printf '{'; separator=
			while read -r part size hash; do
				printf '%s"%s":{"bytes":%s,"sha256":"%s"}' "$separator" "$part" "$size" "$hash"
				separator=,
			done < "$WORKDIR/manifest"
			printf '}'
		else printf null; fi
		printf '}'; separator=,
	done
	printf '}}\n'
}
