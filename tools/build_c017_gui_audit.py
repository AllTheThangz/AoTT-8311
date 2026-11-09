#!/usr/bin/env python3
"""Build the V3 C-017 GUI/backend audit from installed source.

The audit is source-only. It verifies menu-page routing, expected templates,
write-route CSRF/session gates, and named real-Chromium evidence modules.
It performs no device I/O and grants no mutation authorization.
"""
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path
import sys

PAGES = (
    ("config","action_config","8311/config",("test_browser_v3_mib_profile.py","test_browser_v3_boot_config.py")),
    ("pon_status","action_pon_status","8311/pon_status",("test_browser_c017_core_pages.py",)),
    ("pon_explorer","action_pon_explorer","8311/pon_me",("test_browser_pon_explorer.py",)),
    ("vlans","action_vlans","8311/vlans",("test_browser_c017_core_pages.py",)),
    ("support","action_support","8311/support",("test_browser_c017_core_pages.py",)),
    ("firmware","action_firmware","8311/firmware",("test_browser_firmware_boot_plan.py",)),
    ("health","action_r5_health","8311/health",("test_browser_c017_core_pages.py",)),
    ("security","action_r5_security","8311/security",("test_browser_security_tls_key.py",)),
    ("monitoring","action_r8_monitoring","8311/monitoring",("test_browser_monitoring.py",)),
    ("history","action_history","8311/history",("test_browser_history_ui.py","test_browser_history_settings.py")),
    ("management_preflight","action_management_preflight","8311/management_preflight",
        ("test_browser_v3_management_config.py","test_browser_v3_management_confirm.py")),
    ("tls","action_tls","8311/tls",("test_browser_v3_tls_import.py",)),
    ("v3","action_v3","8311/v3",("test_browser_c017_core_pages.py",)),
    ("access","action_access","8311/access",("test_browser_v3_access.py",)),
)
CALL_MUTATORS=("action_firmware","action_firmware_upload","action_support","action_tls_import")

def require(ok,msg):
    if not ok:
        raise ValueError(msg)

def function_body(source,name):
    m=re.search(r"(?ms)^function\s+"+re.escape(name)+r"\([^)]*\)(.*?)(?=^function\s+|\Z)",source)
    require(m is not None,"MISSING_HANDLER_"+name)
    return m.group(1)

def normalize_ws(text):
    return re.sub(r"\s+"," ",text)

def build(root:Path):
    ctl=root/"overlay/usr/lib/lua/luci/controller/8311.lua"
    source=ctl.read_text()
    normalized=normalize_ws(source)
    page_rows=[]
    for route,action,view,browsers in PAGES:
        route_pattern=(
            r'entry\(\{"admin",\s*"8311",\s*"'+re.escape(route)+r'"\},\s*'
            r'call\("'+re.escape(action)+r'"\),\s*translate\('
        )
        require(re.search(route_pattern,normalized) is not None,
                "MISSING_MENU_PAGE_"+route)
        body=function_body(source,action)
        require(('ltemplate.render("'+view+'"') in body,
                "PAGE_VIEW_DRIFT_"+route)
        view_path=root/"overlay/usr/lib/lua/luci/view"/(view+".htm")
        require(view_path.is_file(),"MISSING_VIEW_"+route)
        view_text=view_path.read_text()
        require("<%+header%>" in view_text and "<%+footer%>" in view_text,
                "VIEW_LAYOUT_CONTRACT_"+route)
        for browser in browsers:
            test=root/"tests"/browser
            require(test.is_file(),"MISSING_BROWSER_EVIDENCE_"+route+"_"+browser)
            require("playwright" in test.read_text().lower(),
                    "BROWSER_EVIDENCE_NOT_REAL_"+route+"_"+browser)
        page_rows.append({
            "route":route,"handler":action,"view":view,
            "browser_evidence":list(browsers),"status":"COVERED",
        })

    post_handlers=sorted(set(re.findall(r'post\("([^"]+)"\)',source)))
    require(len(post_handlers)>=24,"POST_HANDLER_COUNT_REGRESSED")
    write_rows=[]
    for handler in post_handlers:
        body=function_body(source,handler)
        require("dispatcher.context.authsession" in body,
                "POST_SESSION_GATE_MISSING_"+handler)
        require("dispatcher.test_post_security" in body,
                "POST_CSRF_GATE_MISSING_"+handler)
        write_rows.append({
            "handler":handler,"route_gate":"post",
            "session_gate":True,"csrf_gate":True,
        })
    for handler in CALL_MUTATORS:
        body=function_body(source,handler)
        require("dispatcher.context.authsession" in body,
                "CALL_MUTATOR_SESSION_GATE_MISSING_"+handler)
        require("dispatcher.test_post_security" in body,
                "CALL_MUTATOR_CSRF_GATE_MISSING_"+handler)
        write_rows.append({
            "handler":handler,"route_gate":"call_mixed_or_multipart",
            "session_gate":True,"csrf_gate":True,
        })

    # Read-only admin data actions that claim GET must explicitly enforce GET.
    get_only=(
        "action_boot_config_status","action_pon_config_status",
        "action_effective_management","action_effective_device","action_effective_pon",
        "action_effective_vlan","action_effective_hardware","action_effective_reporting",
        "action_effective_identity","action_history_data","action_v3_status",
        "action_access_status","action_metrics",
    )
    for handler in get_only:
        body=function_body(source,handler)
        require('REQUEST_METHOD' in body and '"GET"' in body,
                "GET_METHOD_GATE_MISSING_"+handler)

    digest=hashlib.sha256(source.encode()).hexdigest()
    return {
        "schema":1,
        "audit_kind":"V3_C017_GUI_BACKEND_AUDIT",
        "controller_sha256":digest,
        "pages":page_rows,
        "write_actions":write_rows,
        "summary":{
            "menu_pages":len(page_rows),
            "menu_pages_with_real_chromium_evidence":len(page_rows),
            "post_write_handlers":len(post_handlers),
            "mixed_or_multipart_write_handlers":len(CALL_MUTATORS),
            "uncovered_menu_pages":0,
            "write_handlers_missing_session_or_csrf_gate":0,
        },
        "policy":{
            "source_audit_is_not_hardware_qualification":True,
            "browser_evidence_required_for_every_menu_page":True,
            "all_write_actions_require_explicit_session_and_csrf_gate":True,
            "generic_continue_authorizes_live_mutation":False,
        },
        "live_device_queried":False,
        "device_configuration_modified":False,
    }

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root",type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    report=build(args.source_root.resolve(strict=True))
    if args.output:
        out=args.output
        require(out.is_absolute() and out.suffix==".json","OUTPUT_MUST_BE_ABSOLUTE_JSON")
        require(out.parent.resolve(strict=True)==args.source_root.resolve(strict=True)/"docs",
                "OUTPUT_MUST_BE_INSIDE_DOCS")
        require(not out.exists(),"REFUSE_TO_OVERWRITE_C017_AUDIT")
        out.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({
        "status":"C017_GUI_BACKEND_AUDIT_PASS",
        **report["summary"],
        "device_configuration_modified":False,
    },sort_keys=True))

if __name__=="__main__":
    try:
        main()
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print("C017_AUDIT_STOP:"+str(exc)[:220],file=sys.stderr)
        raise SystemExit(1)
