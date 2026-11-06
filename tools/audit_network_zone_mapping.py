#!/usr/bin/env python3
"""Read-only OpenWrt UCI zone-mapping preflight for AoTT-8311.

Consumes privately captured, narrowly filtered UCI network and firewall
snapshots. Never contacts or changes a device. Output contains only generic
findings, not interface addresses or subscriber data. A firewall print plan
is optional and does NOT prove applied kernel rules.
"""
import argparse
import json
from pathlib import Path
import re
import shlex
import sys

SECTION=re.compile(r"^network\.([A-Za-z0-9_-]+)=interface$")
ZONE=re.compile(r"^firewall\.@zone\[(\d+)\]\.(name|network|input)=(.+)$")
DEFAULT=re.compile(r"^firewall\.@defaults\[\d+\]\.input=(.+)$")
INPUT_HOOK=re.compile(
    r"^\s*iptables\s+-t\s+filter\s+-[AI]\s+INPUT\b.*"
    r"\s+-j\s+zone_wan_input(?:\s|$)")

def unquote(value):
    words=shlex.split(value,comments=False,posix=True)
    return words

def assess(network_text, firewall_text, fw3_plan=None):
    ifaces=set()
    for line in network_text.splitlines():
        match=SECTION.fullmatch(line.strip())
        if match:
            ifaces.add(match.group(1))
    zones={}
    defaults=[]
    for line in firewall_text.splitlines():
        line=line.strip()
        m=ZONE.fullmatch(line)
        if m:
            idx,key,val=m.groups()
            entry=zones.setdefault(idx,{})
            values=unquote(val)
            if key=="network":
                entry.setdefault("network",[]).extend(values)
            elif key in ("name","input"):
                if len(values)!=1:
                    raise ValueError("Invalid zone attribute structure")
                entry[key]=values[0]
            continue
        m=DEFAULT.fullmatch(line)
        if m:
            values=unquote(m.group(1))
            if len(values)!=1:
                raise ValueError("Invalid input default structure")
            defaults.append(values[0])
    if not ifaces or len(defaults)!=1 or not zones:
        raise ValueError("Incomplete network interface or firewall zone snapshot")
    wan=[v for v in zones.values() if v.get("name")=="wan"]
    if len(wan)!=1:
        raise ValueError("Exactly one WAN zone is required")
    wan=wan[0]
    refs=wan.get("network",[])
    missing=sorted(set(refs)-ifaces)
    active=sorted(set(refs)&ifaces)
    no_map=not active
    expected_reject=wan.get("input")=="REJECT"
    default_accept=defaults[0]=="ACCEPT"
    generated_wan_hook=(None if fw3_plan is None else
        bool(any(INPUT_HOOK.search(line) for line in fw3_plan.splitlines())))
    risky=no_map or not expected_reject or (default_accept and bool(missing))
    if generated_wan_hook is False:
        risky=True
    return {
        "schema":1,
        "status":"CONFIGURATION_REVIEW_REQUIRED" if risky else "CONFIGURATION_CONSISTENT_KERNEL_UNVERIFIED",
        "global_default_input_accept":default_accept,
        "wan_input_reject_configured":expected_reject,
        "wan_zone_references":len(set(refs)),
        "wan_zone_interface_references_defined":len(active),
        "wan_zone_interface_references_unresolved":len(missing),
        "wan_zone_has_no_defined_interfaces":no_map,
        "generated_ipv4_wan_input_jump_present":generated_wan_hook,
        "kernel_rules_readback_verified":False,
        "external_exposure_tested":False,
        "live_device_modified":False,
    }

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network",required=True,type=Path,
                        help="Privately captured interface names only")
    parser.add_argument("--firewall",required=True,type=Path,
                        help="Privately captured zone name/network/input keys only")
    parser.add_argument("--fw3-print",type=Path,
                        help="Optional sanitized generated fw3 plan (not applied rules)")
    a=parser.parse_args()
    try:
        data=assess(a.network.read_text(encoding="utf-8"),
                    a.firewall.read_text(encoding="utf-8"),
                    a.fw3_print.read_text(encoding="utf-8")
                    if a.fw3_print else None)
    except (OSError,ValueError):
        print(json.dumps({"status":"SNAPSHOT_REJECTED",
                          "error_category":"InvalidOrUnavailableSnapshot"}),
              file=sys.stderr)
        return 2
    print(json.dumps(data,sort_keys=True,indent=2))
    return 1 if data["status"]=="CONFIGURATION_REVIEW_REQUIRED" else 0

if __name__=="__main__":
    raise SystemExit(main())
