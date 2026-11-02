#!/usr/bin/env python3
"""Source-only inventory of configurable PRX126 AoTT-8311 capabilities.

Never connects to an ONU or reads a live boot environment. Parses schema
definitions, source references, and vendor UCI *keys only*. No values,
provisioning, credentials, serials, IP addresses or vendor binary bytes
are serialized. The result is coverage evidence, NOT a functional certification.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

CATEGORY_IDS=("pon","isp","device","sfp","manage")
UPSTREAM_KNOWN_EXTRA={
    "factory_mode":"Upstream 8311 documented debug toggle, absent from current GUI; verify vendor support before exposing.",
    "device_sn":"Upstream 8311 documented device serial setting, not present in current GUI; determine hardware effect before exposing.",
}
EXPECTED_KNOWN_HIDDEN={
    "lct_vlan":"Management VLAN has a commented-out GUI field marked currently broken; needs route/apply/recovery qualification."
}
REGEX_ID=re.compile(r'^\s*id\s*=\s*"([A-Za-z0-9_]+)"')
REGEX_TYPE=re.compile(r'^\s*type\s*=\s*"([A-Za-z0-9_]+)"')
REGEX_OPTION=re.compile(r"^\s*(?:option|list)\s+([A-Za-z_][A-Za-z0-9_]*)\b")
REGEX_SECTION=re.compile(r"^\s*config\s+([A-Za-z_][A-Za-z0-9_]*)\b")


class AuditError(ValueError):pass


def require(value,why):
    if not value:raise AuditError(why)


def safe_source(root):
    root=root.resolve(strict=True)
    require(root.is_dir() and root!=Path("/"),"INVALID_SOURCE_ROOT")
    controller=root/"overlay/usr/lib/lua/luci/controller/8311.lua"
    config=root/"overlay/usr/lib/lua/8311/config.lua"
    require(controller.is_file() and config.is_file() and
            not controller.is_symlink() and not config.is_symlink(),
            "REQUIRED_SOURCE_NOT_FOUND")
    return root,controller,config


def parse_fwenv_form(controller):
    source=controller.read_text()
    require(source.count("function fwenvs_8311()")==1,
            "FIRMWARE_SCHEMA_SIGNATURE_CHANGED")
    body=source.split("function fwenvs_8311()",1)[1].split(
        "\nfunction action_pontop(",1)[0]
    require(body,"FIRMWARE_SCHEMA_FUNCTION_BODY_NOT_FOUND")
    category=None
    rows=[]
    seen=set()
    current=None
    for line in body.splitlines():
        if line.lstrip().startswith("--"):continue
        match=REGEX_ID.match(line)
        if match:
            item=match.group(1)
            if item in CATEGORY_IDS and line.count("\t")<=3:
                category=item
                current=None
                continue
            require(category in CATEGORY_IDS and item not in seen,
                    "DUPLICATE_OR_ORPHANED_GUI_SETTING_"+item)
            row={"id":item,"category":category,"ui_exposed":True,
                 "schema_type":None,
                 "source_server_validation_path":"8311.config.validate",
                 "source_persistent_write_and_readback":"8311.config.apply",
                 "end_to_end_hardware_verified":False,
                 "runtime_consumer_proven":False}
            rows.append(row)
            seen.add(item)
            current=row
            continue
        if current:
            typename=REGEX_TYPE.match(line)
            if typename:
                require(current["schema_type"] is None,
                        "REPEATED_SCHEMA_TYPE_"+current["id"])
                current["schema_type"]=typename.group(1)
    require(len(seen)==len(rows) and all(x["schema_type"] for x in rows),
            "INCOMPLETE_SCHEMA_TYPE_OR_DUPLICATE_FIELD")
    require(set(x["category"] for x in rows)==set(CATEGORY_IDS),
            "UNRECOGNIZED_SCHEMA_CATEGORIES")
    return rows,source


def capture_uci_keys(root):
    # Analyze the offline rootfs only. Never parse or emit any option values.
    rootfs=root/"vendor-rootfs"
    if not rootfs.is_dir():return {}
    config=rootfs/"etc/config"
    if not config.is_dir():return {}
    discovered={}
    for entry in sorted(config.iterdir()):
        if not entry.is_file() or entry.is_symlink():continue
        options=set()
        sections=set()
        for line in entry.read_text(errors="replace").splitlines():
            if line.lstrip().startswith("#"):continue
            m=REGEX_OPTION.match(line)
            if m:options.add(m.group(1))
            m=REGEX_SECTION.match(line)
            if m:sections.add(m.group(1))
        discovered[entry.name]={"section_types":sorted(sections),
                                 "option_names":sorted(options),
                                 "option_count":len(options)}
    return discovered


def inspect(root,rootfs=None):
    root,controller,config=safe_source(root)
    fields,controller_text=parse_fwenv_form(controller)
    core=config.read_text()
    require("function M.snapshot(schema)" in core and
            "function M.prepare(snapshot, form)" in core and
            "function M.apply(snapshot, prepared)" in core and
            'web.digest_text(canonical(items, values))' in core,
            "GENERAL_CONFIG_VALIDATION_READBACK_CONTRACT_CHANGED")
    overlay=root/"overlay"
    text_parts=[]
    for f in sorted(overlay.rglob("*")):
        if not f.is_file() or f.is_symlink():continue
        if (f.suffix not in (".sh",".lua",".htm",".js") and
                f.name not in ("zzz-8311","8311.sh","8311_backend.sh")):
            continue
        try: text_parts.append(f.read_text())
        except UnicodeError:continue
    corpus="\n".join(text_parts)
    for row in fields:
        name=row["id"]
        # Textual consumer evidence is a *hint*, not proof of running effect.
        # Do not mistake the schema definition itself for a runtime consumer.
        row["consumer_reference_present"]=(re.search(
            r"(?:get_8311_|set_8311_|fwenv_get_8311\s+[\(\{]?[\x27\x22]|8311_)"+
            re.escape(name)+r"\b", corpus) is not None)
        row["risk_tier"]="high" if name in (
            "gpon_sn","vendor_id","reg_id_hex","loid","lpwd",
            "pon_mode","mib_file","pon_slot","ipaddr","netmask",
            "gateway","lct_mac","ethtool_speed","bootdelay",
            "uart_select","root_pwhash","persist_root"
        ) else "standard"
    schema_names={f["id"] for f in fields}
    hidden={}
    for field,why in EXPECTED_KNOWN_HIDDEN.items():
        match=re.search(r"^\s*--\s*id\s*=\s*[\x27\x22]"+field+
                        r"[\x27\x22]",controller_text,re.M)
        if match and field not in schema_names:hidden[field]=why
    upstream_missing={k:v for k,v in UPSTREAM_KNOWN_EXTRA.items()
                      if k not in schema_names}
    all_settings=schema_names|set(hidden)|set(upstream_missing)
    actual_counts=dict(Counter(f["category"] for f in fields))
    if rootfs is not None:
        vendor=Path(rootfs).resolve(strict=True)
        require(vendor.is_dir() and vendor!=Path("/"),"INVALID_VENDOR_ROOT")
        config_dir=vendor/"etc/config"
        require(config_dir.is_dir(),"OFFLINE_VENDOR_UCI_DIRECTORY_MISSING")
        uci={}
        for entry in sorted(config_dir.iterdir()):
            if not entry.is_file() or entry.is_symlink():continue
            opts,types=set(),set()
            for line in entry.read_text(errors="replace").splitlines():
                if line.lstrip().startswith("#"):continue
                m=REGEX_OPTION.match(line)
                if m:opts.add(m.group(1))
                m=REGEX_SECTION.match(line)
                if m:types.add(m.group(1))
            uci[entry.name]={"section_types":sorted(types),
                             "option_names":sorted(opts),
                             "option_count":len(opts)}
    else:uci={}
    monitoring=root/"overlay/usr/lib/lua/8311/monitoring.lua"
    health=root/"overlay/usr/lib/lua/8311/health.lua"
    browser=root/"overlay/www/luci-static/resources/view/8311-v2r1.js"
    m=monitoring.read_text() if monitoring.is_file() else ""
    h=health.read_text() if health.is_file() else ""
    b=browser.read_text() if browser.is_file() else ""
    history_source=root/"overlay/usr/lib/lua/8311/history_model.lua"
    history_code=history_source.read_text() if history_source.is_file() else ""
    telemetry={
      "source_only_counter_safe_history_math":(
           "function M.counter_delta" in history_code and
           "function M.eth_rates" in history_code and
           "function M.observe_transition" in history_code),
      "live_optical_and_pon_snapshot_source":'function M.performance()' in h,
      "ethernet_counters_snapshot_source":'ethtool_mac()' in h,
      "gem_port_snapshot_source":'gem_counters()' in h,
      "browser_two_sample_throughput_estimate":'RxGoodBytes' in b and 'TxGoodBytes' in b,
      "optional_remote_syslog_config_source":'function M.send_test()' in m,
      "optional_external_metrics_auth_source":'function M.collector_authorized(getenv)' in m,
      "persistent_local_pon_connectivity_event_history_source":False,
      "persistent_local_throughput_rollups_source":False,
      "end_to_end_isp_wan_reachability_history_source":False,
      "board_neutral_capability_adapter_source":False,
    }
    return {
     "schema_version":1,
     "audit_type":"STATIC_SOURCE_COVERAGE_ONLY_NOT_HARDWARE_VERIFICATION",
     "source_controller_sha256":hashlib.sha256(controller.read_bytes()).hexdigest(),
     "source_config_validator_sha256":hashlib.sha256(config.read_bytes()).hexdigest(),
     "gui_fwenv_count":len(fields),"gui_fwenv_category_counts":actual_counts,
     "gui_fields":fields,
     "known_hidden_fields":hidden,
     "upstream_documented_not_in_gui":upstream_missing,
     "known_candidate_fwenv_names_total":len(all_settings),
     "offline_vendor_uci_config_count":len(uci),
     "offline_vendor_uci_sections":uci,
     "monitoring_capabilities_source_evidence":telemetry,
     "all_configurable_fields_end_to_end_verified":False,
     "cross_hardware_firmware_image_verified":False,
     "source_only":True,"device_queried":False,
     "values_or_identifiers_collected":False,
     "firmware_modified":False,
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root",type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument("--vendor-rootfs",type=Path)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    report=inspect(args.source_root,args.vendor_rootfs)
    if args.output:
        output=args.output
        if not output.is_absolute():raise AuditError("OUTPUT_NEEDS_ABSOLUTE_PATH")
        if output.exists() or output.is_symlink():
            raise AuditError("NEVER_OVERWRITE_PRIOR_COVERAGE_RECEIPT")
        output.parent.mkdir(parents=True,exist_ok=True)
        data=(json.dumps(report,indent=2,sort_keys=True)+"\n").encode()
        fd=__import__("os").open(output,__import__("os").O_WRONLY|
             __import__("os").O_CREAT|__import__("os").O_EXCL|
             __import__("os").O_NOFOLLOW,0o600)
        with __import__("os").fdopen(fd,"wb") as out:out.write(data)
    print(json.dumps({
        "status":"SOURCE_ONLY_CONFIG_CAPABILITY_INVENTORY_PASS",
        "gui_fwenv_fields":report["gui_fwenv_count"],
        "gui_categories":report["gui_fwenv_category_counts"],
        "hidden_known":sorted(report["known_hidden_fields"]),
        "upstream_documented_missing":sorted(report["upstream_documented_not_in_gui"]),
        "offline_uci_config_count":report["offline_vendor_uci_config_count"],
        "history_implemented":report["monitoring_capabilities_source_evidence"]["persistent_local_pon_connectivity_event_history_source"],
        "full_end_to_end_qualification":False,
        "device_accessed":False,
        "output_path":str(args.output) if args.output else None,
    },sort_keys=True))


if __name__=="__main__":
    try:main()
    except (AuditError,ValueError,OSError,KeyError,TypeError) as exc:
        print("CAPABILITY_AUDIT_STOP:"+str(exc)[:190],file=sys.stderr)
        raise SystemExit(1)
