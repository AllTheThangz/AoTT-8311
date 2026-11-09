-- AoTT-8311 vNext C-011: bounded, read-only PRX126 management probes.
--
-- NOT routed anonymously. Integrate only below authenticated LuCI admin.
-- No writes, no reboots, no route mutations, no secret environment reads.
-- Uses only fixed UCI keys and fixed interface names. It does not run
-- arbitrary shell strings from GUI inputs or return full fw_printenv data.
-- A probe failure produces "unavailable", never an invented live value.
local M = {}
local model = require "8311.effective_state"

local IFACES = {"eth0_0_1_lct","mgmt"}
local SECTIONS = {"lct","mgmt"}
local DEFAULT_ROUTE_TARGET=table.concat({"0","0","0","0"},".")
local UCI_KEYS = {"ipaddr","netmask","gateway","dns","macaddr","ifname"}
local ENV_KEYS = {
    "lct_vlan","ipaddr","netmask","gateway","dns_server","pingd",
    "ping_ip","lct_mac","reverse_arp","https_redirect"
}

local function trim(x)
    if type(x)~="string" then return nil end
    if #x>512 or x:find("[%z\1-\31\127]") then
        -- Linux command lines return trailing newlines; strip first.
        x=x:gsub("[\r\n]+$","")
        if x:find("[%z\1-\31\127]") then return nil end
    end
    x=x:match("^%s*(.-)%s*$")
    if #x>128 or x:find("[%z\1-\31\127]") then return nil end
    return x
end

local function verified_interface(name)
    return name=="eth0_0_1_lct" or name=="mgmt"
end

local function sanitize_netifd_status(value,section)
    if type(value)~="table" or (section~="lct" and section~="mgmt") then return nil end
    if type(value.up)~="boolean" then return nil end
    local expected=section=="lct" and "eth0_0_1_lct" or "mgmt"
    if value.up and value.l3_device~=expected and value.device~=expected then return nil end
    local result={probe_ok=true,up=value.up,device=expected,dns={}}
    local addresses=value["ipv4-address"]
    if type(addresses)=="table" and #addresses==1 then
        local row=addresses[1]
        if type(row)=="table" and model.valid_ipv4(row.address) and
           type(row.mask)=="number" and model.dotted_mask(row.mask) then
            result.ipv4=row.address
            result.prefix=row.mask
        end
    elseif type(addresses)=="table" and #addresses>1 then
        return nil
    end
    local routes=value.route
    if type(routes)=="table" then
        local gateway=nil
        for _,row in ipairs(routes) do
            if type(row)=="table" and row.target==DEFAULT_ROUTE_TARGET and row.mask==0 then
                if gateway~=nil then return nil end
                if type(row.nexthop)=="string" and row.nexthop~="" then
                    if not model.valid_ipv4(row.nexthop) then return nil end
                    gateway=row.nexthop
                else
                    gateway=""
                end
            end
        end
        result.gateway=gateway
    end
    local dns=value["dns-server"]
    if type(dns)=="table" then
        if #dns>8 then return nil end
        local seen={}
        for _,server in ipairs(dns) do
            if not model.valid_ipv4(server) or seen[server] then return nil end
            seen[server]=true
            result.dns[#result.dns+1]=server
        end
    end
    return result
end

local function parse_ip_output(body)
    if type(body)~="string" or #body>4096 then return nil end
    local found=nil
    for line in (body.."\n"):gmatch("(.-)\n") do
        if line~="" then
            local ip,prefix=line:match("%sinet%s+(%d+%.%d+%.%d+%.%d+)/(%d+)")
            if not ip then return nil end
            if not model.valid_ipv4(ip) then return nil end
            prefix=tonumber(prefix)
            if not model.dotted_mask(prefix) then return nil end
            if found then return nil end
            found={ipv4=ip,prefix=prefix}
        end
    end
    return found
end

local function parse_route_output(body)
    if type(body)~="string" or #body>8192 then return nil end
    local result={}
    for line in (body.."\n"):gmatch("(.-)\n") do
        if line~="" then
            if #result>=16 or not line:match("^default%s+") then return nil end
            local device=line:match("%sdev%s+([%w_%-%.]+)")
            if not verified_interface(device) then
                -- Unknown/default WAN route may exist. Preserve it only as
                -- "unmapped", never attribute it to the management interface.
                if not device then return nil end
                device="other"
            end
            local via=line:match("%svia%s+(%d+%.%d+%.%d+%.%d+)")
            if via and not model.valid_ipv4(via) then return nil end
            result[#result+1]={dev=device,via=via,
                                onlink=via==nil}
        end
    end
    return result
end

local function capture(adapter)
    if type(adapter)~="table" or type(adapter.uci)~="function" or
       type(adapter.env)~="function" or
       type(adapter.ipv4)~="function" or
       type(adapter.mac)~="function" or
       type(adapter.routes)~="function" or
       type(adapter.ping)~="function" then
        return nil,"invalid_readonly_adapter"
    end
    local safe_call=function(fn,...)
        local good,result=pcall(fn,...)
        if good then return result end
        return nil
    end

    local saved={}
    for _,name in ipairs(ENV_KEYS) do
        local value=safe_call(adapter.env,name)
        if type(value)=="string" and #value<=128 then
            saved[name]=trim(value)
        end
    end

    local uci={uhttpd={}}
    for _,section in ipairs(SECTIONS) do
        local values={}
        for _,key in ipairs(UCI_KEYS) do
            local v=safe_call(adapter.uci,"network",section,key)
            if type(v)=="string" and #v<=128 then
                values[key]=trim(v)
            end
        end
        uci[section]=values
    end
    local vlan_vid=safe_call(adapter.uci,"network","lct_vlan","vid")
    uci.lct_vlan={}
    if type(vlan_vid)=="string" and #vlan_vid<=128 then
        uci.lct_vlan.vid=trim(vlan_vid)
    end
    local redirect=safe_call(adapter.uci,"uhttpd","main","redirect_https")
    if type(redirect)=="string" and #redirect<=128 then
        uci.uhttpd.redirect_https=trim(redirect)
    end

    local kernel={interfaces={},default_routes={},
                  default_route_readable=false}
    for _,iface in ipairs(IFACES) do
        local v=safe_call(adapter.ipv4,iface)
        local m=safe_call(adapter.mac,iface)
        local section={iface_exists=m~=nil}
        if type(v)=="string" then
            local parsed=parse_ip_output(v)
            if parsed then
                section.ipv4=parsed.ipv4
                section.prefix=parsed.prefix
            end
        end
        if type(m)=="string" then
            m=trim(m)
            if m and m:match("^%x%x:%x%x:%x%x:%x%x:%x%x:%x%x$") then
                section.mac=m
            end
        end
        kernel.interfaces[iface]=section
    end
    local route=safe_call(adapter.routes)
    if type(route)=="string" then
        local parsed=parse_route_output(route)
        if parsed then
            kernel.default_routes=parsed
            kernel.default_route_readable=true
        end
    end

    local ping=safe_call(adapter.ping)
    local pingd=type(adapter.daemon)=="function" and safe_call(adapter.daemon,"pingd") or nil
    local rarpd=type(adapter.daemon)=="function" and safe_call(adapter.daemon,"rarpd") or nil
    local http={independent_response_checked=false}
    if type(adapter.http_redirect)=="function" then
        local observed=safe_call(adapter.http_redirect)
        if type(observed)=="table" and
           observed.response_checked==true and
           type(observed.redirects_https)=="boolean" then
            http.independent_response_checked=true
            http.redirects_https=observed.redirects_https
        end
    end
    local netifd={}
    if type(adapter.interface_status)=="function" then
        for _,section in ipairs(SECTIONS) do
            local value=safe_call(adapter.interface_status,section)
            local sanitized=sanitize_netifd_status(value,section)
            if sanitized then netifd[section]=sanitized end
        end
    end
    local active_vlan_id=nil
    if type(adapter.vlan_link)=="function" then
        local raw=safe_call(adapter.vlan_link)
        if type(raw)=="string" and #raw<=4096 then
            local id=raw:match("%svlan%s+protocol%s+802%.1Q%s+id%s+(%d+)")
            if not id then id=raw:match("%svlan%s+id%s+(%d+)") end
            id=tonumber(id)
            if id and id>=1 and id<=4094 and id==math.floor(id) then
                active_vlan_id=id
            end
        end
    end
    local obs={uci=uci,kernel=kernel,
               runtime={ping_target=trim(ping),pingd=pingd,rarpd=rarpd,
                        netifd=netifd,vlan_id=active_vlan_id},
               http=http}
    return model.inspect_management(saved,obs)
end

M.capture=capture
M.parse_ip_output=parse_ip_output
M.parse_route_output=parse_route_output

-- Production read-only adapter. Dependencies are loaded *only* when this
-- function is called, so pure Lua and vendor MIPS fixture tests need none.
-- This source is NOT automatically a public API.
function M.live_management()
    local good, result=pcall(function()
        local uci=require("luci.model.uci").cursor()
        local web=require "8311.webutil"
        local fs=require "nixio.fs"
        local http_probe=require "8311.local_http_probe"
        local daemon_state=require "8311.daemon_state"

        local function bounded(args,max_bytes)
            local code,data,overflow=web.capture(args,max_bytes or 4096)
            if code==0 and not overflow and type(data)=="string" then
                return data
            end
        end
        local adapter={
            uci=function(pkg,section,key)
                return uci:get(pkg,section,key)
            end,
            env=function(name)
                -- "name" always comes from the nine-element constant list.
                return bounded({"/usr/bin/timeout","-k","1","3",
                        "/usr/sbin/fwenv_get","--8311",name},256)
            end,
            ipv4=function(iface)
                if not verified_interface(iface) then return nil end
                return bounded({"/usr/bin/timeout","-k","1","3",
                    "/sbin/ip","-o","-4","addr","show","dev",iface},4096)
            end,
            mac=function(iface)
                if not verified_interface(iface) then return nil end
                return fs.readfile("/sys/class/net/"..iface.."/address",80)
            end,
            routes=function()
                return bounded({"/usr/bin/timeout","-k","1","3",
                    "/sbin/ip","-4","route","show","default"},8192)
            end,
            ping=function()
                return fs.readfile("/tmp/8311-ping-host",96)
            end,
            http_redirect=function()
                local address=uci:get("network","mgmt","ipaddr")
                if not model.valid_ipv4(address) then
                    address=uci:get("network","lct","ipaddr")
                end
                if not model.valid_ipv4(address) then return nil end
                return http_probe.inspect(address)
            end,
            daemon=function(name)
                return daemon_state.read(name)
            end,
            interface_status=function(section)
                if section~="lct" and section~="mgmt" then return nil end
                local code,raw,overflow=web.capture(
                    {"/bin/ubus","call","network.interface."..section,"status"},8192)
                if code~=0 or overflow or type(raw)~="string" then return nil end
                local json=require "luci.jsonc"
                local ok,value=pcall(json.parse,raw)
                return ok and type(value)=="table" and value or nil
            end,
            vlan_link=function()
                local code,raw,overflow=web.capture(
                    {"/sbin/ip","-d","link","show","dev","mgmt"},4096)
                return code==0 and not overflow and raw or nil
            end,
        }
        return capture(adapter)
    end)
    if not good then return nil,"read_only_probe_unavailable" end
    if type(result)~="table" or result.schema~=1 then
        return nil,"read_only_probe_unavailable"
    end
    return result
end

return M
