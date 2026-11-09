-- AoTT-8311 V3 management runtime convergence verifier.
-- Fixed netifd/sysfs sources only. Public receipts contain no addresses, DNS or MAC values.
local fs=require "nixio.fs"
local web=require "8311.webutil"
local json=require "luci.jsonc"
local M={}
local DEFAULT_ROUTE_TARGET=table.concat({"0","0","0","0"},".")

local function ipv4(value)
    if type(value)~="string" then return nil end
    local a,b,c,d=value:match("^(%d+)%.(%d+)%.(%d+)%.(%d+)$")
    if not a then return nil end
    local parts={a,b,c,d}
    local n=0
    for _,p in ipairs(parts) do
        if #p>3 or (#p>1 and p:sub(1,1)=="0") or tonumber(p)>255 then return nil end
        n=n*256+tonumber(p)
    end
    return n
end

local function mask(prefix)
    if type(prefix)~="number" or prefix~=math.floor(prefix) or prefix<0 or prefix>32 then return nil end
    local out={}
    local left=prefix
    for i=1,4 do
        local bits=math.min(8,left)
        local value=0
        for j=1,bits do value=value+2^(8-j) end
        out[i]=tostring(value)
        left=left-bits
    end
    return table.concat(out,".")
end

local function mac(value)
    return type(value)=="string" and
        value:match("^%x%x:%x%x:%x%x:%x%x:%x%x:%x%x$") and value:lower() or nil
end

local function request_ok(r)
    if type(r)~="table" or getmetatable(r)~=nil then return nil end
    local allowed={vlan=true,ipaddr=true,netmask=true,gateway=true,dns_server=true,lct_mac=true}
    for k in pairs(r) do if not allowed[k] then return nil end end
    local vlan=tonumber(r.vlan)
    if type(r.vlan)~="number" and type(r.vlan)~="string" then return nil end
    if not vlan or vlan~=math.floor(vlan) or vlan<0 or vlan>4094 then return nil end
    if not ipv4(r.ipaddr) or not ipv4(r.netmask) then return nil end
    if r.gateway~="" and not ipv4(r.gateway) then return nil end
    if r.dns_server~="" and not ipv4(r.dns_server) then return nil end
    if not mac(r.lct_mac) then return nil end
    return {
        vlan=vlan,ipaddr=r.ipaddr,netmask=r.netmask,gateway=r.gateway,
        dns_server=r.dns_server,lct_mac=r.lct_mac:lower()
    }
end

local function sanitize_status(value,section)
    if type(value)~="table" then return nil,"netifd_status_invalid" end
    local device=section=="mgmt" and "mgmt" or "eth0_0_1_lct"
    if value.up~=true or (value.l3_device~=device and value.device~=device) then
        return nil,"management_interface_not_active"
    end
    local addresses=value["ipv4-address"]
    if type(addresses)~="table" or #addresses~=1 or type(addresses[1])~="table" then
        return nil,"management_ipv4_not_unique"
    end
    local row=addresses[1]
    if not ipv4(row.address) or not mask(row.mask) then return nil,"management_ipv4_invalid" end
    local gateway=nil
    local default_count=0
    if type(value.route)~="table" then return nil,"management_route_status_invalid" end
    for _,route in ipairs(value.route) do
        if type(route)=="table" and route.target==DEFAULT_ROUTE_TARGET and route.mask==0 then
            default_count=default_count+1
            if default_count>1 then return nil,"management_default_route_ambiguous" end
            if route.nexthop==nil or route.nexthop=="" then gateway=""
            elseif ipv4(route.nexthop) then gateway=route.nexthop
            else return nil,"management_default_route_invalid" end
        end
    end
    if default_count==0 then gateway="" end
    local dns={}
    local seen={}
    if type(value["dns-server"])~="table" or #value["dns-server"]>8 then
        return nil,"management_dns_status_invalid"
    end
    for _,server in ipairs(value["dns-server"]) do
        if not ipv4(server) or seen[server] then return nil,"management_dns_status_invalid" end
        seen[server]=true
        dns[#dns+1]=server
    end
    table.sort(dns)
    return {
        section=section,device=device,ipaddr=row.address,netmask=mask(row.mask),
        gateway=gateway,dns=dns
    }
end

local function vlan_id(value)
    if type(value)~="string" or #value>4096 then return nil end
    local id=value:match("%svlan%s+protocol%s+802%.1Q%s+id%s+(%d+)")
    if not id then id=value:match("%svlan%s+id%s+(%d+)") end
    id=tonumber(id)
    if not id or id<1 or id>4094 or id~=math.floor(id) then return nil end
    return id
end

local function compare(request,status,actual_mac,vlan_link)
    local desired=request_ok(request)
    if not desired then return nil,"management_runtime_request_invalid" end
    local expected_section=desired.vlan>0 and "mgmt" or "lct"
    local observed,why=sanitize_status(status,expected_section)
    if not observed then return nil,why end
    local actual=mac(actual_mac)
    if not actual then return nil,"management_runtime_mac_unavailable" end
    if desired.vlan>0 then
        if vlan_id(vlan_link)~=desired.vlan then
            return nil,"management_runtime_vlan_id_mismatch"
        end
    elseif vlan_link~=nil and vlan_link~="" and vlan_id(vlan_link)~=nil then
        return nil,"management_runtime_unexpected_vlan"
    end
    local expected_dns={}
    if desired.dns_server~="" then expected_dns[1]=desired.dns_server end
    local ok=observed.ipaddr==desired.ipaddr and
        observed.netmask==desired.netmask and
        observed.gateway==desired.gateway and
        actual==desired.lct_mac and #observed.dns==#expected_dns
    if ok then
        for i=1,#expected_dns do if observed.dns[i]~=expected_dns[i] then ok=false end end
    end
    if not ok then return nil,"management_runtime_state_mismatch" end
    return {
        schema=1,status="MANAGEMENT_RUNTIME_CONVERGED",
        management_section=expected_section,
        interface_active=true,ipv4_verified=true,netmask_verified=true,
        gateway_verified=true,dns_verified=true,mac_verified=true,
        vlan_mode_verified=true,vlan_id_verified=true,
        contains_configuration_values=false
    }
end
M.verify=compare

function M.live(request)
    local desired=request_ok(request)
    if not desired then return nil,"management_runtime_request_invalid" end
    local section=desired.vlan>0 and "mgmt" or "lct"
    local device=section=="mgmt" and "mgmt" or "eth0_0_1_lct"
    local code,raw,overflow=web.capture(
        {"/bin/ubus","call","network.interface."..section,"status"},8192)
    if code~=0 or overflow or type(raw)~="string" then
        return nil,"management_netifd_status_unavailable"
    end
    local parsed_ok,status=pcall(json.parse,raw)
    if not parsed_ok or type(status)~="table" then
        return nil,"management_netifd_status_invalid"
    end
    local raw_mac=fs.readfile("/sys/class/net/"..device.."/address",80)
    if type(raw_mac)=="string" then raw_mac=raw_mac:gsub("[\r\n]+$","") end
    local vlan_link=nil
    if desired.vlan>0 then
        local vcode,vraw,voverflow=web.capture(
            {"/sbin/ip","-d","link","show","dev","mgmt"},4096)
        if vcode~=0 or voverflow or type(vraw)~="string" then
            return nil,"management_runtime_vlan_link_unavailable"
        end
        vlan_link=vraw
    end
    return compare(desired,status,raw_mac,vlan_link)
end

M.request_ok=request_ok
M.dotted_mask=mask
M.vlan_id=vlan_id
return M
