#!/bin/sh
# Every job owns a fresh workspace and caller-selected destination. Raw vendor
# dumps are opt-in; collection failures are recorded instead of called success.
umask 077
output= cancel_file= full=0 work= worker= partial=0 collected_bytes=0
usage() {
    printf '%s\n' 'Usage: 8311-support.sh --output /absolute/new/archive.tar.gz [--full] [--cancel-file /absolute/path]' >&2
    exit "$1"
}
while [ "$#" -gt 0 ]; do
    case "$1" in
        --output) [ "$#" -ge 2 ] || usage 64; [ -z "$output" ] || usage 64; output=$2; shift;;
        --cancel-file) [ "$#" -ge 2 ] || usage 64; [ -z "$cancel_file" ] || usage 64; cancel_file=$2; shift;;
        --full) full=1;;
        --help|-h) usage 0;;
        *) usage 64;;
    esac
    shift
done
case "$output" in /*) ;; *) usage 64;; esac
case "$cancel_file" in ''|/*) ;; *) usage 64;; esac
case "$output" in */) usage 64;; esac
[ ! -e "$output" ] && [ ! -L "$output" ] || { printf '%s\n' 'support: output already exists' >&2; exit 73; }
parent=${output%/*}; [ -n "$parent" ] || parent=/
[ -d "$parent" ] || { printf '%s\n' 'support: output directory is unavailable' >&2; exit 73; }

cleanup() {
    result=$?
    trap - EXIT HUP INT TERM
    if [ -n "$worker" ]; then
        kill -KILL "$worker" 2>/dev/null
        wait "$worker" 2>/dev/null
    fi
    [ -z "$work" ] || rm -rf "$work"
    exit "$result"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
cancelled() {
    if [ -n "$cancel_file" ] && { [ -e "$cancel_file" ] || [ -L "$cancel_file" ]; }; then
        printf '%s\n' 'support: cancelled' >&2
        exit 130
    fi
}
cancelled
work=$(mktemp -d "$parent/.8311-support.XXXXXX") || exit 73
outdir=$work/support
mkdir "$outdir" || exit 73
mode=sanitized; [ "$full" -eq 0 ] || mode=full
printf 'format=8311-support-v1\nmode=%s\n' "$mode" > "$outdir/collection-status.txt" || exit 74

collect() {
    local name=$1 limit=$2 result raw_bytes error_bytes
    shift 2
    cancelled
    # One command per deadline; no unchecked pipeline hides its exit status.
    (
        # Target BusyBox ash uses 512-byte units. Each regular stdout/stderr
        # capture is capped at 4 MiB, including commands that never terminate.
        ulimit -c 0 && ulimit -f 8192 || exit 74
        timeout -s KILL "$limit" "$@"
    ) > "$work/raw" 2> "$work/errors" &
    worker=$!
    wait "$worker"
    result=$?
    worker=
    cancelled
    raw_bytes=$(stat -c '%s' "$work/raw") || exit 74
    error_bytes=$(stat -c '%s' "$work/errors") || exit 74
    if [ "$raw_bytes" -ge 4194304 ] || [ "$error_bytes" -ge 4194304 ] ||
        [ "$((collected_bytes + raw_bytes))" -gt 25165824 ]; then
        result=74
    fi
    if [ "$result" -eq 0 ]; then
        mv "$work/raw" "$outdir/$name" || exit 74
        collected_bytes=$((collected_bytes + raw_bytes))
        printf '%s=ok\n' "$name" >> "$outdir/collection-status.txt" || exit 74
    else
        partial=1
        printf '%s=failed:%s\n' "$name" "$result" >> "$outdir/collection-status.txt" || exit 74
        # A failed command may have produced a partial or sensitive stream.
        # Keep error status only; do not ship its unchecked stdout/stderr.
        rm -f "$work/raw" || exit 74
    fi
    rm -f "$work/errors" || exit 74
}

collect system.txt 10 uname -a
collect uptime.txt 10 uptime
collect memory.txt 10 free
collect filesystems.txt 10 df -h
collect fwenvs.txt 15 fw_printenv
if [ "$full" -eq 0 ] && [ -f "$outdir/fwenvs.txt" ]; then
    # Default mode never publishes any environment value, including unknown
    # vendor/private keys. Retain key names to show what was configured.
    LC_ALL=C awk -F= '/^[A-Za-z0-9_.-]+=/ { print $1 "=<redacted>" }' \
        "$outdir/fwenvs.txt" > "$work/redacted" &&
        mv "$work/redacted" "$outdir/fwenvs.txt" || exit 74
fi
collect system_log.txt 10 logread
if [ "$full" -eq 0 ] && [ -f "$outdir/system_log.txt" ]; then
    # Ordinary boot logging is fixed separately. Historical or vendor lines
    # naming credentials/identity are omitted wholesale in default archives.
    LC_ALL=C awk '
        { l=tolower($0) }
        l ~ /password|passwd|pwhash|lpwd|loid|registration|reg_id|gpon_sn|serial|pon sn|authorization|credential|private.key|token|secret|\$[156y]\$/ { omitted++; next }
        { print }
        END { printf "[8311 support: %d sensitive log lines omitted]\n", omitted }
    ' "$outdir/system_log.txt" > "$work/redacted" &&
        mv "$work/redacted" "$outdir/system_log.txt" || exit 74
fi
collect tc_filters.txt 20 8311-tc-filter-dump.sh
if [ "$full" -eq 1 ]; then
    collect omci_pipe_md.txt 95 omci_pipe.sh md
    collect omci_pipe_mda.txt 95 omci_pipe.sh mda
    collect extvlan-tables.txt 30 8311-extvlan-decode.sh -t
    collect extvlan-decoded.txt 30 8311-extvlan-decode.sh
fi
cat > "$outdir/README.txt" <<'INFO'
Default sanitized mode redacts every environment value and omits log lines
naming authentication material or subscriber identity. Raw OMCI and extended
VLAN dumps are collected only with --full. Review before sharing: other logs,
traffic filters, hostnames and network topology can still identify a system.
Full mode includes raw environment values and vendor dumps and is sensitive.
The pontop batch dump is omitted because its fixed /tmp/pontop.txt destination
cannot safely belong to concurrent jobs. No stale shared dump is imported.
collection-status.txt lists each attempted command and its result. Failed
command output is excluded. Exit 2 means this archive is a partial collection.
Each stdout/stderr capture is limited to 4 MiB. Successful raw captures total
at most 24 MiB, before any redaction. The final archive is limited to 32 MiB
and passes gzip integrity and tar readability checks before publication.
INFO
[ "$?" -eq 0 ] || exit 74
printf 'captured_raw_bytes=%s\nresult=%s\n' "$collected_bytes" "$(if [ "$partial" -eq 0 ]; then printf complete; else printf partial; fi)" >> "$outdir/collection-status.txt" || exit 74
cancelled
(
    ulimit -c 0 && ulimit -f 65536 || exit 74
    timeout -s KILL 60 tar -czf "$work/archive.tar.gz" -C "$work" support
) >/dev/null 2>/dev/null &
worker=$!
wait "$worker"
archive_result=$?
worker=
[ "$archive_result" -eq 0 ] || exit 74
[ -s "$work/archive.tar.gz" ] || exit 74
archive_bytes=$(stat -c '%s' "$work/archive.tar.gz") || exit 74
[ "$archive_bytes" -le 33554432 ] || exit 74
cancelled
timeout -s KILL 30 gzip -t "$work/archive.tar.gz" >/dev/null 2>/dev/null || exit 74
cancelled
timeout -s KILL 30 tar -tzf "$work/archive.tar.gz" >/dev/null 2>/dev/null || exit 74
cancelled
# Hard-link publication is atomic and fails if the caller path exists, even
# if another job wins the destination name after the initial check.
ln -T "$work/archive.tar.gz" "$output" || exit 73
printf 'support: %s archive ready\n' "$mode"
if [ "$partial" -eq 1 ]; then
    printf '%s\n' 'support: one or more collections failed; see collection-status.txt' >&2
    exit 2
fi
exit 0
