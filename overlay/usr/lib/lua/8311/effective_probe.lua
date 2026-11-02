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
local UCI_KEYS = {"ipaddr","netmask","gateway","dns","macaddr","ifname"}
local ENV_KEYS = {
    "ipaddr","netmask","gateway","dns_server","pingd",
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
    local obs={uci=uci,kernel=kernel,runtime={ping_target=trim(ping)},
               http={independent_response_checked=false}}
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
