-- C-011: dependency-free read-only management effective-state tests.
-- Fixture values are synthetic RFC documentation IPs, never live subscriber data.
-- Compatible with host and vendor big-endian MIPS Lua 5.1.
local root=assert(arg[1],"overlay Lua root required")
package.path=root.."/?.lua;"..package.path
local model=require "8311.effective_state"
local probe=require "8311.effective_probe"
local count=0

local function ok(x,label)
    count=count+1
    assert(x,"EFFECTIVE_MANAGEMENT_FIXTURE_FAILED:"..label)
end
local function eq(a,b,label)
    ok(a==b,label)
end
local function ip(a,b,c,d)
    return table.concat({a,b,c,d},".")
end
local function mac(a,b,c,d,e,f)
    return table.concat({a,b,c,d,e,f},":")
end

local A=ip(192,0,2,10)
local ROUTER=ip(192,0,2,1)
local OTHER=ip(192,0,2,25)
local DNS=ip(198,51,100,53)
local MAC=mac("02","ab","cd","ef","01","02")
local OTHER_MAC=mac("02","ab","cd","ef","99","88")
local saved={
    ipaddr=A,netmask=ip(255,255,255,0),gateway=ROUTER,
    dns_server=DNS,pingd="1",ping_ip=ROUTER,lct_mac=MAC,
    reverse_arp="1",https_redirect="1"
}
local uci={
    lct={ipaddr=A,netmask=ip(255,255,255,0),gateway=ROUTER,
         dns=DNS,macaddr=MAC,ifname="eth0_0_1_lct"},
    mgmt={},uhttpd={redirect_https="1"},
}
local addresses={
    eth0_0_1_lct="4: eth0_0_1_lct    inet "..A.."/24 brd "..ip(192,0,2,255)..
                   " scope global eth0_0_1_lct\n",
    mgmt="",
}
local macs={eth0_0_1_lct=MAC.."\n"}
local route="default via "..ROUTER.." dev eth0_0_1_lct proto static\n"
local ping=ROUTER.."\n"
local reads={}
local adapter={
    uci=function(pkg,section,key)
        reads[#reads+1]=pkg.."."..section.."."..key
        local r=pkg=="uhttpd" and uci.uhttpd or (uci[section] or {})
        return r[key]
    end,
    env=function(name)
        reads[#reads+1]="env."..name
        return saved[name] and saved[name].."\n" or nil
    end,
    ipv4=function(dev)
        reads[#reads+1]="ip."..dev
        return addresses[dev]
    end,
    mac=function(dev)
        reads[#reads+1]="mac."..dev
        return macs[dev]
    end,
    routes=function()
        reads[#reads+1]="route"
        return route
    end,
    ping=function()
        reads[#reads+1]="ping"
        return ping
    end,
}
local baseline,err=probe.capture(adapter)
ok(baseline~=nil,"baseline_sample")
eq(err,nil,"baseline_no_error")
eq(baseline.management_section,"lct","lct_selected")
eq(baseline.management_interface,"eth0_0_1_lct","lct_actual_iface")
eq(baseline.no_device_write,true,"no_write")
eq(baseline.no_reboot,true,"no_reboot")
eq(baseline.no_hidden_hardware_qualification,true,"not_claim_hardware_qualification")
eq(baseline.fields.ipaddr.configured_source,"uci_lct","uci_source")
eq(baseline.fields.ipaddr.observed_source,"kernel_ipv4_interface","kernel_address")
eq(baseline.fields.ipaddr.configured_to_observed,"match","live_and_uci_match")
eq(baseline.fields.ipaddr.saved_to_observed,"match","live_and_saved_match")
eq(baseline.fields.ipaddr.runtime_effect_proven,true,"active_ipv4_observed")
eq(baseline.fields.netmask.observed_value,ip(255,255,255,0),"live_ipv4_prefix")
eq(baseline.fields.netmask.runtime_effect_proven,true,"active_mask_observed")
eq(baseline.fields.gateway.observed_source,"kernel_default_route_via","route_from_kernel")
eq(baseline.fields.gateway.configured_to_observed,"match","route_match")
eq(baseline.fields.lct_mac.observed_value,MAC,"kernel_mac_normalized")
eq(baseline.fields.lct_mac.runtime_effect_proven,true,"kernel_mac_observed")
eq(baseline.fields.dns_server.configured_value,DNS,"uci_dns_config")
eq(baseline.fields.dns_server.runtime_effect_proven,false,"dns_not_verified_from_uci")
eq(baseline.fields.https_redirect.configured_value,"1","uci_https_redirect")
eq(baseline.fields.https_redirect.runtime_effect_proven,false,"redirect_requires_http_probe")
eq(baseline.fields.pingd.runtime_effect_proven,false,"pingd_proc_not_proof")
eq(baseline.fields.reverse_arp.runtime_effect_proven,false,"rarp_proc_not_proof")
eq(baseline.fields.ping_ip.observed_value,ROUTER,"cached_ping_target")
eq(baseline.fields.ping_ip.runtime_effect_proven,false,"cached_ping_not_proof")
eq(baseline.summary.kernel_observed,4,"four_kernel_values_observed")
eq(baseline.summary.effective_and_saved_match,4,"four_kernel_saved_matches")
eq(baseline.summary.drift_from_saved,0,"no_saved_drift")
ok(#reads>=27 and #reads<=32,"fixed_read_only_probes_run")
for _,request in ipairs(reads) do
    ok(not request:find("gpon_sn",1,true) and
       not request:find("root_pwhash",1,true) and
       not request:find("reg_id",1,true) and
       not request:find("lpwd",1,true),"no_subscriber_secret_getter")
end

-- A changed saved value does not rewrite the kernel observed value.
saved.ipaddr=OTHER
local mismatch=assert(probe.capture(adapter))
eq(mismatch.fields.ipaddr.saved_to_configured,"mismatch","saved_vs_uci_drift")
eq(mismatch.fields.ipaddr.saved_to_observed,"mismatch","saved_vs_kernel_drift")
eq(mismatch.fields.ipaddr.configured_to_observed,"match","uci_still_matches_kernel")
eq(mismatch.summary.drift_from_saved,1,"count_drift")
saved.ipaddr=A

-- UCI may be correct while the *actual* kernel address differs.
addresses.eth0_0_1_lct="4: eth0_0_1_lct inet "..OTHER.."/24 scope global\n"
local live_drift=assert(probe.capture(adapter))
eq(live_drift.fields.ipaddr.configured_to_observed,"mismatch","kernel_drift_from_uci")
eq(live_drift.fields.ipaddr.saved_to_observed,"mismatch","kernel_drift_from_saved")
eq(live_drift.fields.ipaddr.runtime_effect_proven,true,"real_kernel_value_not_hidden")
addresses.eth0_0_1_lct="4: eth0_0_1_lct inet "..A.."/24 scope global\n"

-- HTTP is not called by the probe. A separately corroborated response
-- is the only way to promote redirect from configured to observed.
local source=assert(probe.capture(adapter))
eq(source.fields.https_redirect.runtime_effect_proven,false,"http_source_only")
local explicit=assert(model.inspect_management(saved,{
    uci=uci,kernel={interfaces={
        eth0_0_1_lct={ipv4=A,prefix=24,mac=MAC,iface_exists=true}
    },default_route_readable=true,default_routes={
        {dev="eth0_0_1_lct",via=ROUTER}
    }},
    http={independent_response_checked=true,redirects_https=true}
}))
eq(explicit.fields.https_redirect.runtime_effect_proven,true,"http_true_response_proven")
eq(explicit.fields.https_redirect.saved_to_observed,"match","http_matches_saved")

-- Management VLAN addresses must be read from mgmt, NOT stale lct.
uci.mgmt={
    ipaddr=OTHER,netmask=ip(255,255,255,0),gateway=ROUTER,
    dns=DNS,macaddr=OTHER_MAC,ifname="mgmt",
}
uci.lct.ipaddr=nil
addresses.eth0_0_1_lct=""
addresses.mgmt="8: mgmt inet "..OTHER.."/24 scope global mgmt\n"
macs.mgmt=OTHER_MAC.."\n"
route="default via "..ROUTER.." dev mgmt proto static\n"
local vlan=assert(probe.capture(adapter))
eq(vlan.management_section,"mgmt","management_vlan_selected")
eq(vlan.fields.ipaddr.observed_value,OTHER,"vlan_runtime_address")
eq(vlan.fields.lct_mac.observed_value,OTHER_MAC,"vlan_active_mac")
eq(vlan.fields.ipaddr.saved_to_observed,"mismatch","vlan_changed_from_saved")

-- Both interfaces having IPs cannot be silently resolved by choosing
-- whichever UCI section is more convenient.
addresses.eth0_0_1_lct="4: eth0_0_1_lct inet "..A.."/24\n"
local ambiguous=assert(probe.capture(adapter))
eq(ambiguous.management_section,"undetermined","multiple_interfaces_conflict")
eq(ambiguous.selection_reason,"multiple_live_management_interfaces","ambiguity_message")
eq(ambiguous.fields.ipaddr.runtime_effect_proven,false,"no_false_kernel_check")
eq(ambiguous.fields.ipaddr.configured_source,"unavailable","no_fabricated_uci_section")
addresses.eth0_0_1_lct=""

-- No management IP in the kernel: show UCI only, not applied.
addresses.mgmt=""
local unbound=assert(probe.capture(adapter))
eq(unbound.management_section,"mgmt","uci_intended_only_fallback")
eq(unbound.fields.ipaddr.configured_value,OTHER,"configured_not_lost")
eq(unbound.fields.ipaddr.runtime_effect_proven,false,"no_kernel_address_not_success")
eq(unbound.fields.ipaddr.observed_value,nil,"no_fake_effective_ip")
addresses.mgmt="8: mgmt inet "..OTHER.."/24 scope global\n"

-- Failure injection: independent probes may fail, but must not report
-- a fake running value, crash or invent success.
local originalip=adapter.ipv4
adapter.ipv4=function()error("synthetic read failure")end
local noip=assert(probe.capture(adapter))
eq(noip.fields.ipaddr.runtime_effect_proven,false,"ip_failure_not_success")
adapter.ipv4=originalip
local originalroute=adapter.routes
adapter.routes=function()error("synthetic timeout")end
local noroute=assert(probe.capture(adapter))
eq(noroute.fields.gateway.runtime_effect_proven,false,"route_failure_not_success")
adapter.routes=originalroute

-- Unknown routes cannot be claimed as absent from the target interface.
route="not a default route\n"
local invalidroute=assert(probe.capture(adapter))
eq(invalidroute.fields.gateway.runtime_effect_proven,false,"unknown_route_not_absent")
route="default via "..ROUTER.." dev mgmt proto static\n"

-- An actual zero-route result proves only the absence of the management
-- default route, not absence of any other route or WAN service.
route=""
local none=assert(probe.capture(adapter))
eq(none.fields.gateway.observed_source,"kernel_no_management_default_route","no_route_evidence")
eq(none.fields.gateway.observed_value,"","explicitly_empty_route")
route="default via "..ROUTER.." dev mgmt proto static\n"

-- Probe output format changes must fail closed.
eq(probe.parse_ip_output("malformed vendor response"),nil,"unknown_ip_output")
eq(probe.parse_route_output("default strange syntax"),nil,"unknown_route_output")
eq(probe.parse_route_output("junk line"),nil,"junk_route_rejected")
eq(probe.parse_ip_output(
    "1: mgmt inet "..A.."/24\n2: mgmt inet "..OTHER.."/24\n"),nil,
    "multiple_ipv4_candidates_no_guess")

-- No dynamic, unsupported interface can be queried by adapter.
local extra=0
local unsafe= {
    uci=adapter.uci,env=adapter.env,
    ipv4=function(dev)
        extra=extra+1
        ok(dev=="mgmt" or dev=="eth0_0_1_lct","fixed_interface_only")
        return ""
    end,
    mac=adapter.mac,routes=adapter.routes,ping=adapter.ping,
}
local safe=assert(probe.capture(unsafe))
eq(extra,2,"never_probe_arbitrary_device")

local nope,why=probe.capture({})
eq(nope,nil,"invalid_adapter_nil")
eq(why,"invalid_readonly_adapter","invalid_adapter_reason")
local invalid,reason=model.inspect_management(nil,{})
eq(invalid,nil,"nil_saved_table_rejected")
eq(reason,"invalid_management_input","invalid_input_reason")

ok(count>=85,"fixture_substantial")
print("AOTT_C011_EFFECTIVE_STATE_FIXTURE_PASS checks="..count)
