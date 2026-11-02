-- AoTT-8311 vNext C-011: pure read-only management state interpreter.
--
-- Input must come from a trusted, independently bounded read-only probe.
-- This model performs no I/O and does not read firmware environment secrets.
-- UCI saved configuration is not the same as a running kernel effect.
-- Do not call a property hardware-qualified just because a source
-- implementation or UCI option exists.
local M = {}

local MANAGE = {
    "ipaddr", "netmask", "gateway", "dns_server", "pingd",
    "ping_ip", "lct_mac", "reverse_arp", "https_redirect"
}
local IFACE = {lct="eth0_0_1_lct", mgmt="mgmt"}
local MAX_STRING = 128

local function valid_text(v)
    if type(v) ~= "string" or #v > MAX_STRING or
       v:find("[%z\1-\31\127]") then return nil end
    return v
end

local function text(v)
    return valid_text(v) or nil
end

local function bounded_ipv4(v)
    if not valid_text(v) then return nil end
    local a,b,c,d = v:match("^(%d+)%.(%d+)%.(%d+)%.(%d+)$")
    if not a then return nil end
    local t={a,b,c,d}
    for i=1,4 do
        local x=t[i]
        if #x>3 or (#x>1 and x:sub(1,1)=="0") or
           tonumber(x)>255 then return nil end
    end
    return v
end

local function mac(v)
    if not valid_text(v) or not
       v:match("^%x%x:%x%x:%x%x:%x%x:%x%x:%x%x$") then
        return nil
    end
    return v:lower()
end

local function dotted_mask(prefix)
    if type(prefix)~="number" or prefix~=math.floor(prefix) or
       prefix<0 or prefix>32 then return nil end
    local bytes={}
    local remaining=prefix
    for i=1,4 do
        local n=math.min(8,remaining)
        local value=0
        for j=1,n do value=value+2^(8-j) end
        bytes[i]=tostring(value)
        remaining=remaining-n
    end
    return table.concat(bytes,".")
end

local function selected_interface(uci,kernel)
    local lct=(uci or {}).lct or {}
    local mgmt=(uci or {}).mgmt or {}
    local interfaces=(kernel or {}).interfaces or {}
    local lct_value=interfaces[IFACE.lct] or {}
    local mgmt_value=interfaces[IFACE.mgmt] or {}
    local lct_up=bounded_ipv4(lct_value.ipv4)~=nil
    local mgmt_up=bounded_ipv4(mgmt_value.ipv4)~=nil
    if lct_up and mgmt_up then return nil,"multiple_live_management_interfaces" end
    if mgmt_up then return "mgmt","kernel_address_detected" end
    if lct_up then return "lct","kernel_address_detected" end
    -- UCI alone may name an unbound interface. Do not infer kernel success.
    if bounded_ipv4(mgmt.ipaddr) and not bounded_ipv4(lct.ipaddr) then
        return "mgmt","uci_intended_only"
    end
    if bounded_ipv4(lct.ipaddr) and not bounded_ipv4(mgmt.ipaddr) then
        return "lct","uci_intended_only"
    end
    return nil,"no_unique_live_management_interface"
end

local function compare(a,b,normalizer)
    local left=normalizer and normalizer(a) or text(a)
    local right=normalizer and normalizer(b) or text(b)
    if left==nil or left=="" or right==nil or right=="" then
        return "unverified"
    end
    return left==right and "match" or "mismatch"
end

local function field(id,saved)
    return {
        id=id,
        saved_value=text(saved),
        configured_value=nil,
        observed_value=nil,
        configured_source="unavailable",
        observed_source="unavailable",
        saved_to_configured="unverified",
        configured_to_observed="unverified",
        saved_to_observed="unverified",
        runtime_effect_proven=false,
        persist_after_reboot_proven=false,
        recovery_proven=false,
        hardware_qualified=false,
        notes={},
    }
end

local function note(item,value)
    item.notes[#item.notes+1]=value
end

local function configure(item,value,kind,normalizer)
    item.configured_value=text(value)
    if item.configured_value~=nil then
        item.configured_source=kind
        item.saved_to_configured=compare(item.saved_value,
                                           item.configured_value,normalizer)
    end
end

local function observe(item,value,kind,normalizer,effect_proof)
    item.observed_value=text(value)
    if item.observed_value~=nil then
        item.observed_source=kind
        item.configured_to_observed=compare(
            item.configured_value,item.observed_value,normalizer)
        item.saved_to_observed=compare(
            item.saved_value,item.observed_value,normalizer)
        item.runtime_effect_proven=effect_proof==true
    end
end

local function binary(v)
    if v=="1" or v=="on" then return "1" end
    if v=="0" or v=="off" then return "0" end
    return nil
end

local function route_for(kernel,dev)
    if not dev or type(kernel)~="table" then return nil end
    if kernel.default_route_readable~=true then return nil end
    local routes=kernel.default_routes
    if type(routes)~="table" then return nil end
    local seen=0
    local selected=nil
    for _,route in ipairs(routes) do
        if type(route)=="table" and route["dev"]==dev then
            seen=seen+1
            selected=route
        end
    end
    if seen>1 then return {ambiguous=true} end
    if seen==0 then return {none=true} end
    return selected
end

function M.inspect_management(saved,probes)
    if type(saved)~="table" or type(probes)~="table" then
        return nil,"invalid_management_input"
    end
    local uci=probes.uci or {}
    local kernel=probes.kernel or {}
    if type(uci)~="table" or type(kernel)~="table" then
        return nil,"invalid_probe_structure"
    end
    local section,reason=selected_interface(uci,kernel)
    local cfg=section and uci[section] or {}
    local dev=section and IFACE[section] or nil
    local actual=dev and ((kernel.interfaces or {})[dev] or {}) or {}
    local result={
        schema=1,
        source="read_only_management_observation",
        management_section=section or "undetermined",
        management_interface=dev or "undetermined",
        selection_reason=reason,
        no_device_write=true,
        no_reboot=true,
        no_hidden_hardware_qualification=true,
        fields={},
    }
    for _,id in ipairs(MANAGE) do
        result.fields[id]=field(id,saved[id])
    end

    for _,id in ipairs({"ipaddr","netmask","gateway","lct_mac"}) do
        local cfgkey=id=="lct_mac" and "macaddr" or id
        local item=result.fields[id]
        configure(item,cfg[cfgkey],"uci_"..(section or "unresolved"),id=="lct_mac" and mac or nil)
    end
    configure(result.fields.dns_server,cfg.dns,"uci_"..(section or "unresolved"),nil)
    configure(result.fields.https_redirect,(uci.uhttpd or {}).redirect_https,"uci_uhttpd",binary)

    if section~=nil then
        local address=bounded_ipv4(actual.ipv4)
        if address then
            observe(result.fields.ipaddr,address,"kernel_ipv4_interface",bounded_ipv4,true)
        else
            note(result.fields.ipaddr,"kernel_interface_ipv4_unavailable")
        end
        local mask=dotted_mask(actual.prefix)
        if address and mask then
            observe(result.fields.netmask,mask,"kernel_ipv4_prefix",nil,true)
        else
            note(result.fields.netmask,"kernel_ipv4_prefix_unavailable")
        end
        local actualmac=mac(actual.mac)
        if actualmac and actual.iface_exists==true then
            observe(result.fields.lct_mac,actualmac,"kernel_sysfs_mac",mac,true)
        else
            note(result.fields.lct_mac,"kernel_mac_unavailable")
        end
        local route=route_for(kernel,dev)
        if route then
            if route.ambiguous then
                note(result.fields.gateway,"ambiguous_management_default_routes")
            elseif route.none then
                -- An absent management default gateway is explicitly
                -- observed, not a claim that global Internet routes work.
                observe(result.fields.gateway,"","kernel_no_management_default_route",
                        bounded_ipv4,true)
            elseif bounded_ipv4(route.via) then
                observe(result.fields.gateway,route.via,"kernel_default_route_via",
                        bounded_ipv4,true)
            elseif route.onlink then
                note(result.fields.gateway,"onlink_route_has_no_ipv4_next_hop")
            else
                note(result.fields.gateway,"unrecognized_default_route")
            end
        else
            note(result.fields.gateway,"kernel_default_route_unavailable")
        end
    else
        for _,id in ipairs({"ipaddr","netmask","gateway","lct_mac","dns_server"}) do
            note(result.fields[id],reason)
        end
    end

    -- DNS in UCI is only configuration. It does not prove an active
    -- resolver, that DNS server is reachable, or any Internet access.
    note(result.fields.dns_server,"uci_dns_is_not_effective_resolver_evidence")

    -- Pingd and reverse ARP daemons loop even when disabled. A process
    -- PID alone is not evidence that packets are actually being sent.
    for _,id in ipairs({"pingd","reverse_arp"}) do
        local item=result.fields[id]
        item.configured_source="boot_environment_only"
        note(item,"running_daemon_does_not_prove_feature_enabled")
    end
    local ping=result.fields.ping_ip
    local target=bounded_ipv4((probes.runtime or {}).ping_target)
    if target then
        observe(ping,target,"runtime_cached_ping_target",bounded_ipv4,false)
        note(ping,"cached_target_does_not_prove_ping_sent")
    else
        note(ping,"runtime_ping_target_unavailable")
    end

    -- HTTP redirect requires a real HTTP response probe. A uhttpd UCI
    -- option, even with a matching saved environment, is not proof.
    local h=(probes.http or {})
    if h.independent_response_checked==true and
       (h.redirects_https==true or h.redirects_https==false) then
        observe(result.fields.https_redirect,
                h.redirects_https and "1" or "0",
                "independent_http_response",binary,true)
    else
        note(result.fields.https_redirect,"http_redirect_requires_response_probe")
    end

    local counts={kernel_observed=0,configured_only=0,unverified=0,
                  effective_and_saved_match=0,drift_from_saved=0}
    for _,id in ipairs(MANAGE) do
        local item=result.fields[id]
        if item.runtime_effect_proven then
            counts.kernel_observed=counts.kernel_observed+1
        elseif item.configured_value~=nil then
            counts.configured_only=counts.configured_only+1
        else
            counts.unverified=counts.unverified+1
        end
        -- A cached target is an observed value but not proof of a
        -- running service. Never count it as effective convergence.
        if item.runtime_effect_proven and item.saved_to_observed=="match" then
            counts.effective_and_saved_match=counts.effective_and_saved_match+1
        elseif item.runtime_effect_proven and item.saved_to_observed=="mismatch" then
            counts.drift_from_saved=counts.drift_from_saved+1
        end
    end
    result.summary=counts
    return result
end

M.management_fields=MANAGE
M.dotted_mask=dotted_mask
M.valid_ipv4=bounded_ipv4
return M
