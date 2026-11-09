-- AoTT-8311 V3 independent runtime verifier for access/server settings.
local util=require "luci.util"
local web=require "8311.webutil"
local uci_lib=require "luci.model.uci"
local remote_firewall=require "8311.remote_firewall"
local M={}

local function running_instance(name)
    local record=util.ubus("service","list",{name=name})
    local svc=type(record)=="table" and record[name]
    local instances=type(svc)=="table" and svc.instances
    if type(instances)~="table" then return nil,"service_instances_unavailable" end
    local found={}
    for _,instance in pairs(instances) do
        if type(instance)=="table" and instance.running==true and type(instance.command)=="table" then
            found[#found+1]=instance
        end
    end
    if #found==0 then return nil,"service_not_running" end
    if #found~=1 then return nil,"service_instance_not_unique" end
    return found[1]
end

local function argv_model(command,executable)
    if type(command)~="table" or command[1]~=executable then return nil end
    local flags={present={},values={},multi={}}
    local i=2
    while i<=#command do
        local token=command[i]
        if type(token)~="string" then return nil end
        flags.present[token]=true
        local takes={
            ["-p"]=true,["-s"]=true,["-K"]=true,["-I"]=true,["-T"]=true,
            ["-W"]=true,["-l"]=true,["-t"]=true,["-N"]=true,["-n"]=true,
            ["-k"]=true,["-A"]=true,["-h"]=true,["-r"]=true,["-x"]=true,
            ["-u"]=true,["-C"]=true,["-L"]=true,
        }
        if takes[token] then
            local value=command[i+1]
            if type(value)~="string" then return nil end
            if token=="-p" or token=="-s" then
                flags.multi[token]=flags.multi[token] or {}
                flags.multi[token][#flags.multi[token]+1]=value
            else
                if flags.values[token]~=nil then return nil end
                flags.values[token]=value
            end
            i=i+2
        else
            i=i+1
        end
    end
    return flags
end

local function same_list(a,b)
    if type(a)~="table" or type(b)~="table" or #a~=#b then return false end
    local counts={}
    for _,v in ipairs(a) do counts[v]=(counts[v] or 0)+1 end
    for _,v in ipairs(b) do
        if not counts[v] or counts[v]<1 then return false end
        counts[v]=counts[v]-1
    end
    return true
end

local function mdns_ok(instance,enabled,port)
    local data=instance.data
    local mdns=type(data)=="table" and data.mdns
    if enabled=="0" then return mdns==nil or next(mdns)==nil end
    if type(mdns)~="table" then return false end
    for _,entry in pairs(mdns) do
        if type(entry)=="table" and entry.service=="_ssh._tcp.local" and
           tonumber(entry.port)==tonumber(port) then return true end
    end
    return false
end

local function dropbear(snapshot)
    local v=snapshot.values
    local instance,why=running_instance("dropbear")
    if v.ssh_enabled=="0" then
        if instance then return nil,"dropbear_running_while_disabled" end
        if why=="service_not_running" or why=="service_instances_unavailable" then
            return {verified=true,running=false}
        end
        return nil,why
    end
    if not instance then return nil,why end
    local m=argv_model(instance.command,"/usr/sbin/dropbear")
    if not m or not m.present["-F"] then return nil,"dropbear_command_invalid" end
    if m.values["-p"]~=v.ssh_port then return nil,"dropbear_port_mismatch" end
    if (m.present["-s"] and "0" or "1")~=v.ssh_password_auth then
        return nil,"dropbear_password_auth_mismatch"
    end
    if (m.present["-g"] and "0" or "1")~=v.ssh_root_password_auth then
        return nil,"dropbear_root_password_auth_mismatch"
    end
    if (m.present["-w"] and "0" or "1")~=v.ssh_root_login then
        return nil,"dropbear_root_login_mismatch"
    end
    if (m.present["-a"] and "1" or "0")~=v.ssh_gateway_ports then
        return nil,"dropbear_gateway_ports_mismatch"
    end
    local expected_k=v.ssh_keepalive~="0" and v.ssh_keepalive or nil
    local expected_i=v.ssh_idle_timeout~="0" and v.ssh_idle_timeout or nil
    if m.values["-K"]~=expected_k then return nil,"dropbear_keepalive_mismatch" end
    if m.values["-I"]~=expected_i then return nil,"dropbear_idle_timeout_mismatch" end
    if m.values["-T"]~=v.ssh_max_auth_tries then return nil,"dropbear_max_auth_tries_mismatch" end
    if not mdns_ok(instance,v.ssh_mdns,v.ssh_port) then return nil,"dropbear_mdns_mismatch" end
    return {verified=true,running=true}
end

local function uhttpd(snapshot)
    local v=snapshot.values
    local instance,why=running_instance("uhttpd")
    if not instance then return nil,why end
    local m=argv_model(instance.command,"/usr/sbin/uhttpd")
    if not m or not m.present["-f"] then return nil,"uhttpd_command_invalid" end
    if not same_list(m.multi["-p"] or {},snapshot.http_listeners or {}) then
        return nil,"uhttpd_http_listener_mismatch"
    end
    if not same_list(m.multi["-s"] or {},snapshot.https_listeners or {}) then
        return nil,"uhttpd_https_listener_mismatch"
    end
    local expected={
        ["-t"]=v.web_script_timeout,["-T"]=v.web_network_timeout,
        ["-k"]=v.web_http_keepalive,["-A"]=v.web_tcp_keepalive,
        ["-n"]=v.web_max_requests,["-N"]=v.web_max_connections,
    }
    for flag,value in pairs(expected) do
        if m.values[flag]~=value then return nil,"uhttpd_runtime_flag_mismatch_"..flag end
    end
    if (m.present["-R"] and "1" or "0")~=v.web_rfc1918_filter then
        return nil,"uhttpd_rfc1918_filter_mismatch"
    end
    return {verified=true,running=true}
end

local SESSION_PROBE=[[local c=require "luci.config";io.write(tostring(c.sauth and c.sauth.sessiontime or ""))]]
local function sessiontime(snapshot)
    local code,out,overflow=web.capture({"/usr/bin/lua","-e",SESSION_PROBE},128)
    if code~=0 or overflow or type(out)~="string" then return nil,"luci_session_probe_failed" end
    out=out:gsub("[\r\n]+$","")
    if out~=snapshot.values.luci_sessiontime then return nil,"luci_sessiontime_runtime_mismatch" end
    return {verified=true}
end

function M.verify(snapshot)
    if type(snapshot)~="table" or snapshot.schema~=1 or type(snapshot.values)~="table" then
        return nil,"access_runtime_snapshot_invalid"
    end
    local ssh,why=dropbear(snapshot);if not ssh then return nil,why end
    local webrec,wwhy=uhttpd(snapshot);if not webrec then return nil,wwhy end
    local session,swhy=sessiontime(snapshot);if not session then return nil,swhy end
    local firewall,fwhy=remote_firewall.verify(uci_lib.cursor(),
        snapshot.management_ip,snapshot.values.web_https_port,
        snapshot.values.remote_gui_enabled,
        snapshot.values.remote_gui_ipv4_sources)
    if not firewall then return nil,fwhy end
    return {
        schema=1,status="ACCESS_RUNTIME_VERIFIED",
        ssh_runtime_verified=true,web_runtime_verified=true,
        luci_session_runtime_verified=true,
        remote_firewall_verified=true,
        remote_firewall_enabled=firewall.enabled,
        remote_firewall_rule_count=firewall.rule_count,
        firewall_kernel_packet_path_unverified=true,
        contains_configuration_values=false,
    }
end

M.argv_model=argv_model
return M
