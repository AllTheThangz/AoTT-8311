#!/bin/sh
# Operator-run, read-only baseline for the physical PRX126/MIPS stick.
# No setters, service actions, bank selection, cache deletion or full env dump.
# The native reader may acquire/create its ordinary advisory lock file.
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
ulimit -c 0 2>/dev/null || :
arch=$(uname -m 2>/dev/null) || exit 2
case "$arch" in mips*) ;; *) printf '%s\n' 'REFUSED: run on the MIPS ONU itself, not Hermes'; exit 2;; esac
printf 'architecture=%s\n' "$arch"
printf 'kernel='; uname -r
for file in /usr/sbin/fw_printenv /usr/sbin/fwenv_get /usr/sbin/fwenv_set /lib/libc.so /lib/libgcc_s.so.1; do
    if [ -f "$file" ] && command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$file"
    else
        printf 'unavailable=%s\n' "$file"
    fi
done
if [ -r /proc/mounts ]; then
    awk '$2=="/" || $2=="/tmp" || $2=="/overlay" || $2=="/ptconf" {
        n=split($4,a,","); mode="unknown";
        for(i=1;i<=n;i++) if(a[i]=="ro" || a[i]=="rw") mode=a[i];
        printf "mount=%s filesystem=%s mode=%s\n",$2,$3,mode
    }' /proc/mounts
fi
if [ -r /etc/fw_env.config ]; then
    awk '$1 ~ /^\/dev\/mtd[0-9]+$/ && $2 ~ /^0x[0-9A-Fa-f]+$/ && $3 ~ /^0x[0-9A-Fa-f]+$/ {
        printf "env_layout=%s offset=%s size=%s\n",$1,$2,$3; found=1
    } END { if(!found) print "env_layout=unclassified_not_exported" }' /etc/fw_env.config
else
    printf '%s\n' 'env_layout=unavailable'
fi
if [ -x /usr/bin/timeout ] && [ -x /usr/sbin/fw_printenv ]; then
    # Exactly one non-secret management key. Never print raw output, which
    # could include fallback diagnostics. A missing key is not called success.
    observed=$(/usr/bin/timeout -k 1 5 /usr/sbin/fw_printenv -n -- 8311_lct_vlan 2>&1)
    status=$?
    printf 'native_reader_exit=%s\n' "$status"
    case "$observed" in
        ''|*[!0-9]*) printf '%s\n' 'native_reader_output=empty_or_diagnostic_not_exported';;
        *) if [ "$status" -eq 0 ] && [ "${#observed}" -le 4 ] && [ "$observed" -le 4094 ]; then
               printf '%s\n' 'native_reader_output=valid_scoped_vlan'
           else
               printf '%s\n' 'native_reader_output=unqualified_not_exported'
           fi;;
    esac
else
    printf '%s\n' 'native_reader=not_run_required_tool_unavailable'
fi
printf '%s\n' 'settings_changed=no' 'full_environment_exported=no'
