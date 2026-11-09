#!/usr/bin/env python3
"""Build the V3 C-016 vendor capability classification registry.

This is source-only discovery. It inspects option NAMES and native consumer
source in an offline vendor rootfs. It never reads live settings or option
values, never mutates a device, and never converts source discovery into a
hardware qualification claim.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import sys

import audit_configurability as audit

GUI_MAP = {
    ("gpon","iop_mask"): "iop_mask",
    ("gpon","nSerial"): "gpon_sn",
    ("gpon","pon_mode"): "pon_mode",
    ("gpon","regID"): "reg_id_hex",
    ("luci","lang"): "lang",
    ("uhttpd","redirect_https"): "https_redirect",
}
TLS_MANAGED = {
    "bits","cert","commonname","country","days","ec_curve","key","key_type",
    "location","state",
}
UHTTPD_PRODUCT = {
    "listen_http","listen_https","script_timeout","network_timeout",
    "http_keepalive","tcp_keepalive","max_requests","max_connections",
    "rfc1918_filter",
}
LUCi_PRODUCT = {"sessiontime"}
DROPBEAR_PRODUCT = {
    "PasswordAuth","RootPasswordAuth","Port","RootLogin","SSHKeepAlive",
    "IdleTimeout","MaxAuthTries","GatewayPorts","mdns","enable",
}
DROPBEAR_DEPENDENCY = {"DirectInterface"}
DROPBEAR_EXPERT = {
    "Interface","ForceCommand","BannerFile","RecvWindowSize","keyfile",
    "rsakeyfile",
}
GPON_EXPERIMENTAL = {
    "key_size","mode","plev_cap","ploam_timeout_0","ploam_timeout_1",
    "ploam_timeout_2","ploam_timeout_3","ploam_timeout_4","ploam_timeout_5",
    "ploam_timeout_6","ploam_timeout_cpi","ploam_timeout_cpl","psk",
}
FRAMEWORK_DOMAINS = {"firewall","rpcd","ucitrack"}
LUCI_FRAMEWORK = {
    "display","dropbear","enable","firewall","holdoff","mediaurlbase",
    "openvpn","opkg","passwd","resourcebase","rollback","sessionpath",
    "timeout","ubuspath","uci","uploads",
}
UHTTPD_INTERNAL = {
    "cgi_prefix","home","lua_prefix","alias","config","error_page","httpauth",
    "index_page","interpreter","lua_handler","lua_prefix_LENGTH","no_dirlists",
    "no_symlinks","no_ubusauth","password","prefix","realm","ubus_cors",
    "ubus_prefix","ubus_socket","username",
}

DROPBEAR_VALIDATE = re.compile(
    r"""['"]([A-Za-z][A-Za-z0-9_]*):(?:bool|string|file|list\(file\)|port|uinteger)(?::[^'"]*)?['"]"""
)
UHTTPD_APPEND = re.compile(
    r"""append_(?:arg|bool)\s+["']?\$cfg["']?\s+([A-Za-z][A-Za-z0-9_]*)"""
)
UHTTPD_GET = re.compile(
    r"""config_get(?:_bool)?\s+\S+\s+["']?\$cfg["']?\s+([A-Za-z][A-Za-z0-9_]*)"""
)
UHTTPD_LIST = re.compile(
    r"""config_list_foreach\s+["']?\$cfg["']?\s+([A-Za-z][A-Za-z0-9_]*)"""
)

def require(ok: bool, why: str) -> None:
    if not ok:
        raise ValueError(why)

def source_option_sets(vendor: Path) -> dict[str,set[str]]:
    drop=(vendor/"etc/init.d/dropbear").read_text(errors="replace")
    uhttpd=(vendor/"etc/init.d/uhttpd").read_text(errors="replace")
    return {
        "dropbear": set(DROPBEAR_VALIDATE.findall(drop)),
        "uhttpd": (
            set(UHTTPD_APPEND.findall(uhttpd)) |
            set(UHTTPD_GET.findall(uhttpd)) |
            set(UHTTPD_LIST.findall(uhttpd))
        ),
    }

def classify(domain: str, option: str) -> tuple[str,str,str|None]:
    gui=GUI_MAP.get((domain,option))
    if gui:
        return "EXISTING_AOTT_CONTROL","mapped_to_existing_aott_field",gui
    if domain=="dropbear":
        if option in DROPBEAR_DEPENDENCY:
            return "DEPENDENCY_MANAGED","owned_by_guarded_management_transaction",None
        if option in DROPBEAR_PRODUCT:
            return "PRODUCT_CONTROL_CANDIDATE","native_dropbear_runtime_option",None
        if option in DROPBEAR_EXPERT:
            return "EXPERT_CONTROL_CANDIDATE","native_dropbear_advanced_option",None
        return "INTERNAL_OR_UNCLASSIFIED","dropbear_option_requires_review",None
    if domain=="uhttpd":
        if option in TLS_MANAGED:
            return "SUBSYSTEM_MANAGED","owned_by_tls_certificate_manager",None
        if option in UHTTPD_PRODUCT:
            risk="guarded_listener_control_required" if option in {"listen_http","listen_https"} else "native_uhttpd_runtime_option"
            return "PRODUCT_CONTROL_CANDIDATE",risk,None
        if option in UHTTPD_INTERNAL:
            return "INTERNAL_FRAMEWORK","luci_webstack_internal_path",None
        return "INTERNAL_OR_UNCLASSIFIED","uhttpd_option_requires_review",None
    if domain=="gpon":
        if option in GPON_EXPERIMENTAL:
            return "EXPERIMENTAL_TEST_OLT","low_level_pon_option_requires_spare_or_test_olt",None
        return "INTERNAL_OR_UNCLASSIFIED","gpon_option_requires_consumer_trace",None
    if domain=="luci":
        if option in LUCi_PRODUCT:
            return "PRODUCT_CONTROL_CANDIDATE","native_luci_session_runtime_option",None
        if option in LUCI_FRAMEWORK:
            return "INTERNAL_FRAMEWORK","luci_framework_or_module_plumbing",None
        return "INTERNAL_OR_UNCLASSIFIED","luci_option_requires_review",None
    if domain in FRAMEWORK_DOMAINS:
        return "INTERNAL_FRAMEWORK",domain+"_schema_primitive_not_discrete_product_capability",None
    if domain in {"ieee_1588","omci","optic","serdes","sfp_eeprom","tod"}:
        return "NO_OPTION_NAMES_IN_VENDOR_CONFIG","domain_present_without_named_options",None
    return "INTERNAL_OR_UNCLASSIFIED","domain_requires_review",None

def build(source: Path, vendor: Path) -> dict:
    source=source.resolve(strict=True)
    vendor=vendor.resolve(strict=True)
    require(source.is_dir() and vendor.is_dir(),"INVALID_SOURCE_OR_VENDOR_ROOT")
    base=audit.inspect(source,vendor)
    runtime=source_option_sets(vendor)
    existing={
        d:set(rec["option_names"])
        for d,rec in base["offline_vendor_uci_sections"].items()
    }
    domains=set(existing)|set(runtime)
    rows=[]
    for domain in sorted(domains):
        all_options=set(existing.get(domain,set()))|set(runtime.get(domain,set()))
        if not all_options:
            rows.append({
                "id":"uci:"+domain,
                "domain":domain,"option":None,
                "present_in_vendor_config":True,
                "native_runtime_consumer_discovered":False,
                "classification":"NO_OPTION_NAMES_IN_VENDOR_CONFIG",
                "reason":"domain_present_without_named_options",
                "hardware_qualified":False,
            })
            continue
        for option in sorted(all_options):
            kind,reason,mapped=classify(domain,option)
            rows.append({
                "id":"uci:"+domain+":"+option,
                "domain":domain,"option":option,
                "present_in_vendor_config":option in existing.get(domain,set()),
                "native_runtime_consumer_discovered":
                    option in runtime.get(domain,set()),
                "classification":kind,
                "reason":reason,
                "mapped_aott_field":mapped,
                "editable_by_this_registry":False,
                "hardware_qualified":False,
            })
    counts=Counter(r["classification"] for r in rows)
    product=[
        r["id"] for r in rows
        if r["classification"] in {"PRODUCT_CONTROL_CANDIDATE","EXPERT_CONTROL_CANDIDATE"}
    ]
    experimental=[
        r["id"] for r in rows if r["classification"]=="EXPERIMENTAL_TEST_OLT"
    ]
    unclassified=[
        r["id"] for r in rows if r["classification"]=="INTERNAL_OR_UNCLASSIFIED"
    ]
    return {
        "schema":1,
        "status":"C016_VENDOR_CAPABILITY_CLASSIFICATION_SOURCE_ONLY",
        "hardware_profile":"potron-prx126-aott-v1",
        "vendor_config_domains":base["offline_vendor_uci_config_count"],
        "vendor_config_option_names":
            sum(rec["option_count"] for rec in base["offline_vendor_uci_sections"].values()),
        "native_runtime_supported_dropbear_options":sorted(runtime["dropbear"]),
        "native_runtime_supported_uhttpd_options":sorted(runtime["uhttpd"]),
        "capabilities":rows,
        "summary":{
            "classified_records":len(rows),
            "by_classification":dict(sorted(counts.items())),
            "product_or_expert_candidates":len(product),
            "test_olt_experimental_candidates":len(experimental),
            "unclassified_remaining":len(unclassified),
            "mapped_existing_aott_controls":
                counts.get("EXISTING_AOTT_CONTROL",0),
        },
        "product_or_expert_candidate_ids":product,
        "test_olt_experimental_candidate_ids":experimental,
        "unclassified_ids":unclassified,
        "policy":{
            "framework_schema_options_are_not_counted_as_individual_product_features":True,
            "source_discovery_is_not_hardware_qualification":True,
            "no_live_mutation_authorized":True,
            "test_olt_options_require_spare_or_test_olt":True,
        },
        "source_only":True,
        "live_device_queried":False,
        "device_configuration_modified":False,
        "contains_runtime_values_or_credentials":False,
    }

def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-root",type=Path,default=Path(__file__).resolve().parents[1])
    ap.add_argument("--vendor-rootfs",type=Path,required=True)
    ap.add_argument("--output",type=Path)
    args=ap.parse_args()
    report=build(args.source_root,args.vendor_rootfs)
    if args.output:
        output=args.output
        require(output.is_absolute() and output.suffix==".json","OUTPUT_MUST_BE_ABSOLUTE_JSON")
        require(output.parent.resolve(strict=True)==args.source_root.resolve(strict=True)/"docs",
                "OUTPUT_MUST_BE_IN_DOCS")
        require(not output.exists() and not output.is_symlink(),"REFUSE_OVERWRITE")
        data=(json.dumps(report,indent=2,sort_keys=True)+"\n").encode()
        os.umask(0o077)
        fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,"wb") as f:
            f.write(data);f.flush();os.fsync(f.fileno())
    print(json.dumps({
        "status":report["status"],
        **report["summary"],
        "output":str(args.output) if args.output else None,
    },sort_keys=True))

if __name__=="__main__":
    try:
        main()
    except (OSError,ValueError,KeyError,TypeError,audit.AuditError) as exc:
        print("C016_CAPABILITY_STOP:"+str(exc)[:180],file=sys.stderr)
        raise SystemExit(1)
