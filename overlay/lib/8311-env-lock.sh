#!/bin/sh
# One stable inode serializes environment readers and complete write batches.
# Firmware callers acquire their firmware lock BEFORE this lock. Children may
# inherit FD 8; they close it on release but must never unlock their parent's FD.

lock_environment() {
    local path=/tmp/8311-environment.lock uid inode inherited elapsed
    if [ "${_8311_ENV_LOCK_DEPTH:-0}" -gt 0 ]; then
        _8311_ENV_LOCK_DEPTH=$((_8311_ENV_LOCK_DEPTH + 1))
        return 0
    fi
    uid=$(id -u) || return 73
    if [ -e "$path" ] || [ -L "$path" ]; then
        [ ! -L "$path" ] && [ -f "$path" ] || return 73
        [ "$(stat -c '%u' "$path")" = "$uid" ] || return 73
        case "$(stat -c '%a' "$path")" in *[2367][0-7]|*[0-7][2367]) return 73;; esac
    else
        # noclobber prevents following a path created between the checks.
        (umask 077; set -C; : > "$path") 2>/dev/null || {
            [ ! -L "$path" ] && [ -f "$path" ] || return 73
        }
    fi
    [ ! -L "$path" ] && [ -f "$path" ] || return 73
    [ "$(stat -c '%u' "$path")" = "$uid" ] || return 73
    case "$(stat -c '%a' "$path")" in *[2367][0-7]|*[0-7][2367]) return 73;; esac
    inode=$(stat -c '%d:%i' "$path") || return 73
    inherited=$(stat -Lc '%d:%i' /proc/self/fd/8 2>/dev/null) || inherited=
    _8311_ENV_LOCK_OWNED=0
    if [ "$inherited" != "$inode" ]; then
        exec 8>>"$path" || return 73
        _8311_ENV_LOCK_OWNED=1
    fi
    [ ! -L "$path" ] && [ -f "$path" ] &&
        [ "$(stat -Lc '%d:%i' /proc/self/fd/8)" = "$inode" ] &&
        [ "$(stat -c '%d:%i' "$path")" = "$inode" ] || { exec 8>&-; return 73; }
    elapsed=0
    until flock -n 8; do
        [ "$elapsed" -lt 30 ] || { exec 8>&-; return 75; }
        sleep 1
        elapsed=$((elapsed + 1))
    done
    _8311_ENV_LOCK_DEPTH=1
}

unlock_environment() {
    local result=0
    [ "${_8311_ENV_LOCK_DEPTH:-0}" -gt 0 ] || return 0
    _8311_ENV_LOCK_DEPTH=$((_8311_ENV_LOCK_DEPTH - 1))
    [ "$_8311_ENV_LOCK_DEPTH" -eq 0 ] || return 0
    if [ "${_8311_ENV_LOCK_OWNED:-0}" -eq 1 ]; then
        flock -u 8 || result=74
    fi
    exec 8>&-
    _8311_ENV_LOCK_OWNED=0
    return "$result"
}
