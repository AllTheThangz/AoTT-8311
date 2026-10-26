#!/bin/sh
TC=$(PATH=/usr/sbin:/sbin /usr/bin/which tc)

tc() { "$TC" "$@"; }

# Selectors contain validated interface names and fixed numeric rule slots.
tc_flower_selector() {
    local dev= direction= handle= protocol= pref= only=0
    [ "$1" != -devdironly ] || { only=1; shift; }
    while [ "$#" -gt 0 ]; do
        case "$1" in
            dev) dev=$2; shift;;
            ingress|egress) direction=$1;;
            handle) handle=$2; shift;;
            protocol) [ -n "$protocol" ] || protocol=$2; shift;;
            pref) pref=$2; shift;;
            flower) break;;
        esac
        shift
    done
    case "$dev" in ''|*[!a-zA-Z0-9_.:-]*) return 64;; esac
    case "$direction" in ingress|egress) ;; *) return 64;; esac
    if [ "$only" -eq 1 ]; then
        printf 'dev %s %s\n' "$dev" "$direction"
    else
        case "$handle:$pref:$protocol" in *[!a-zA-Z0-9_.:]*|::*|*::*) return 64;; esac
        [ -n "$handle" ] && [ -n "$pref" ] && [ -n "$protocol" ] || return 64
        printf 'dev %s %s handle %s pref %s protocol %s flower\n' "$dev" "$direction" "$handle" "$pref" "$protocol"
    fi
}

tc_flower_get() {
    local selector
    selector=$(tc_flower_selector "$@") || return "$?"
    tc filter get $selector
}
tc_flower_exists() { tc_flower_get "$@" >/dev/null 2>&1; }
tc_exists() { tc filter get "$@" >/dev/null 2>&1; }

# A failed get is not proof of absence. A successful listing of the exact
# protocol/preference must also contain no matching handle.
tc_flower_absent() {
    local selector listing devdir handle pref protocol
    selector=$(tc_flower_selector "$@") || return "$?"
    set -- $selector
    devdir="dev $2 $3"; handle=$5; pref=$7; protocol=$9
    listing=$(tc filter show $devdir protocol "$protocol" pref "$pref" flower) || return 74
    printf '%s\n' "$listing" | awk -v handle="$handle" '
        function number(s, n,i,c) {
            s=tolower(s); if (s !~ /^0x/) return s+0
            n=0; for(i=3;i<=length(s);i++) { c=index("0123456789abcdef",substr(s,i,1))-1; if(c<0)return -1; n=n*16+c }; return n
        }
        { for(i=1;i<NF;i++) if($i=="handle" && number($(i+1))==number(handle)) found=1 }
        END { exit found ? 1 : 0 }
    '
}

tc_flower_del() {
    local selector
    selector=$(tc_flower_selector "$@") || return "$?"
    if tc_flower_exists "$@"; then
        tc filter del $selector || return "$?"
    fi
    tc_flower_absent "$@"
}

# Strictly compare the subset of flower/action shapes emitted by the builtin
# fixer. Unknown match keys, extra actions, software fallback, and malformed
# output fail closed instead of treating selector existence as correct content.
tc_flower_matches() {
    local actual expected="$*"
    actual=$(tc_flower_get "$@") || return 1
    printf '%s\n' "$actual" | awk -v expected="$expected" '
        function number(s, n,i,c) {
            s=tolower(s); if(s !~ /^0x/)return s+0
            n=0; for(i=3;i<=length(s);i++){c=index("0123456789abcdef",substr(s,i,1))-1;if(c<0)return -1;n=n*16+c};return n
        }
        BEGIN {
            n=split(expected,a," "); ekey=""; eprio=""; eproto="802.1q"
            for(i=1;i<=n;i++) {
                if(a[i]=="handle") eh=number(a[i+1])
                if(a[i]=="pref") ep=a[i+1]
                if(a[i]=="protocol" && !outer) { outer=tolower(a[i+1]) }
                if(a[i]=="vlan_id") ekey=a[i+1]
                if(a[i]=="action") {
                    ekind=a[i+1]; if(ekind=="vlan") emode=a[i+2]
                    for(j=i+1;j<=n;j++) {
                        if(a[j]=="id") evid=a[j+1]
                        if(a[j]=="priority") eprio=a[j+1]
                        if(a[j]=="protocol") eproto=tolower(a[j+1])
                    }
                    break
                }
            }
        }
        {
            line=$0; sub(/^[ \t]+/,"",line)
            if(line=="") next
            if(line ~ /^action order [0-9]+:/) { actions++; inaction=1 }
            if(!inaction) {
                if(line !~ /^(filter |eth_type |vlan_id |skip_sw($| )|in_hw($| )|not_in_hw($| )|in_hw_count )/) bad=1
                for(i=1;i<=NF;i++) {
                    if($i=="handle") { handles++; if(number($(i+1))!=eh)bad=1 }
                    if($i=="pref" && $(i+1)!=ep)bad=1
                    if($i=="protocol" && tolower($(i+1))!=outer)bad=1
                    if($i=="eth_type" && tolower($(i+1))!=outer)bad=1
                    if($i=="vlan_id") { keys++; key=$(i+1) }
                    if($i=="skip_sw") skip=1
                    if($i=="not_in_hw") bad=1
                    if($i=="in_hw_count" && $(i+1)<1)bad=1
                    if($i=="chain" && $(i+1)!=0)bad=1
                    if($i=="classid")bad=1
                }
            } else if(line ~ /^action order [0-9]+:/) {
                if(ekind=="drop") { if(line !~ /gact action drop([ \t]|$)/)bad=1 }
                else {
                    if(line !~ /vlan[ \t]+(pop|push|modify)([ \t]|$)/)bad=1
                    for(i=1;i<=NF;i++) {
                        if($i=="vlan" && $(i+1)!=emode)bad=1
                        if($i=="id") vid=$(i+1)
                        if($i=="protocol") proto=tolower($(i+1))
                        if($i=="priority") prio=$(i+1)
                        if($i=="pass") pass=1
                    }
                }
            } else if(line !~ /^(index |ref |bind |installed |used |Sent |backlog |random type none )/) bad=1
        }
        END {
            if(handles!=1 || actions!=1 || !skip || bad)exit 1
            if(ekey=="" ? keys!=0 : (keys!=1 || key!=ekey))exit 1
            if(ekind!="drop") {
                if(!pass)exit 1
                if(emode!="pop" && (vid!=evid || proto!=eproto))exit 1
                if(eprio!="" && prio!=eprio)exit 1
                if(eprio=="" && prio!="" && prio!=0)exit 1
            }
        }
    '
}

tc_flower_ensure() {
    local attempt
    tc_flower_matches "$@" && return 0
    for attempt in 1 2; do
        # Delete only this reserved selector. Never clear a whole direction.
        tc_flower_del "$@" || return "$?"
        if tc filter add "$@" && tc_flower_matches "$@"; then return 0; fi
    done
    return 1
}

# Generic hook API supports action types beyond the builtin verifier. Its
# existence check does not claim semantic content verification. Hooks can use
# replace for an explicit desired change, or ensure for builtin rule shapes.
tc_flower_add() {
    tc_flower_exists "$@" && return 0
    tc_flower_absent "$@" || return "$?"
    tc filter add "$@" && tc_flower_exists "$@"
}
tc_flower_replace() {
    tc_flower_del "$@" && tc filter add "$@" && tc_flower_exists "$@"
}

# Kept for explicit custom hooks; builtin reconciliation never invokes a broad
# clear. Hook authors are responsible for the scope they deliberately request.
tc_flower_clear() {
    local selector
    selector=$(tc_flower_selector -devdironly "$@") || return "$?"
    tc filter del $selector
}
