-- Isolated integration of the *actual vendor LuCI UCI model* and AoTT monitoring.
-- Uses synthetic UCI state and mocked ubus. No live device, flash or network.
local vendor_uci = assert(arg[1], "vendor LuCI UCI source")
local monitoring_path = assert(arg[2], "AoTT monitoring module")
local system = {
    [".name"]="cfg0a", [".type"]="system",
    log_remote="0", log_proto="udp", log_port="514"
}
local network = {
    lct={[".name"]="lct", [".type"]="interface", ipaddr="192" .. ".0.2.1"}
}
local staged, calls, restarts = {}, {}, 0
local deleted = {}
local DELETED = {}
local last_digest = nil
local current_snapshot = nil

local function copy(src)
    local result = {}
    for k,v in pairs(src or {}) do result[k]=v end
    return result
end
local function current_system()
    local result = copy(system)
    for k,v in pairs(staged) do
        if v == DELETED then result[k]=nil else result[k]=v end
    end
    return result
end
package.preload["luci.util"] = function()
    return {
        ubus=function(service,operation,args)
            assert(service == "uci", "Unexpected ubus service")
            assert(type(args) == "table", "Missing ubus UCI args")
            calls[#calls+1] = {operation=operation, config=args.config}
            if operation == "get" then
                if args.config == "system" and args.type == "system" then
                    return {values={cfg0a=current_system()}}
                elseif args.config == "system" and args.section == "cfg0a" then
                    if args.option then
                        local v=current_system()[args.option]
                        return v and {value=v} or nil, not v and 4 or nil
                    end
                    return {values=current_system()}
                elseif args.config == "network" then
                    local v=network[args.section]
                    return v and {values=copy(v)} or nil, not v and 4 or nil
                end
                return nil, 4
            elseif operation == "set" then
                assert(args.config == "system" and args.section == "cfg0a")
                for k,v in pairs(args.values) do
                    assert(type(k)=="string" and type(v)=="string")
                    staged[k]=v
                end
                return {}
            elseif operation == "delete" then
                assert(args.config == "system" and args.section == "cfg0a")
                staged[args.option]=DELETED
                return {}
            elseif operation == "changes" then
                assert(args.config == "system")
                return {changes=copy(staged)}
            elseif operation == "revert" then
                staged={}
                return {}
            elseif operation == "commit" then
                assert(args.config == "system")
                for k,v in pairs(staged) do
                    if v==DELETED then system[k]=nil else system[k]=v end
                end
                staged={}
                return {}
            end
            error("Unexpected UCI command " .. tostring(operation))
        end
    }
end
package.preload["8311.webutil"] = function()
    return {
        digest_text=function(plaintext)
            -- Only a deterministic fixture digest, never production hashing.
            local n=0
            for i=1,#plaintext do n=(n*31+plaintext:byte(i)) % 999983 end
            return string.format("%064x",n)
        end,
        lock=function(path)
            assert(path=="/tmp/8311-monitoring.lock")
            return {close=function() end}
        end,
        capture=function(argv)
            if argv[5]=="/etc/init.d/log" and argv[6]=="reload" then
                restarts=restarts+1
                return 0,"",false
            end
            error("Unexpected subprocess")
        end
    }
end
package.preload["luci.sys"] = function()
    return {uniqueid=function(bytes)
        assert(bytes==32)
        return string.rep("c",64)
    end}
end
assert(loadfile(vendor_uci))()
local uci = assert(package.loaded["luci.model.uci"])
assert(uci.cursor(), "vendor module did not register cursor")
local mon=assert(loadfile(monitoring_path))()
local state=assert(mon.snapshot())
assert(state.log_remote=="0" and state.log_port=="514")
assert(uci.cursor():get("system","cfg0a","not_present")==false,
       "Vendor Lua UCI must report missing field as false")
local _,why,status=mon.apply({
    revision=state.revision,log_remote="0",log_ip="",
    log_port="514",log_proto="udp",aott_metrics="1",
    aott_metrics_client="192" .. ".0.2.40"
})
assert(status==422 and why:find("token"),"Must require read-only token")
assert(#calls>0)
local issued=assert(mon.change_credential(state.revision,"rotate"))
assert(issued.collector_token==string.rep("c",64))
assert(system.aott_metrics_sha256~=issued.collector_token)
local form={
    revision=issued.revision,log_remote="0",log_ip="",
    log_port="514",log_proto="udp",aott_metrics="1",
    aott_metrics_client="192" .. ".0.2.40"
}
local applied,reason,code=mon.apply(form)
assert(applied and code==200 and not reason,reason)
assert(restarts==0,"Unchanged logging settings must not restart daemon")
assert(applied.credential_configured and applied.aott_metrics=="1")
assert(mon.metrics_enabled())
local env={HTTPS="on",REMOTE_ADDR="192"..".0.2.40",
           SERVER_ADDR="192"..".0.2.1",
           HTTP_X_AOTT_METRICS_TOKEN=issued.collector_token}
assert(mon.collector_authorized(function(k)return env[k] end))
env.HTTP_X_FORWARDED_FOR=env.REMOTE_ADDR
env.REMOTE_ADDR="192"..".0.2.41"
assert(not mon.collector_authorized(function(k)return env[k]end))
env.REMOTE_ADDR="192"..".0.2.40"
local rev=assert(mon.change_credential(mon.snapshot().revision,"revoke"))
assert(rev.credential_configured==false)
assert(not mon.metrics_enabled())
assert(not mon.collector_authorized(function(k)return env[k]end))
assert(system.aott_metrics_sha256==nil)
-- Explicitly show why ordinary rootfs UCI is not an A/B persistence
-- guarantee: the model loses settings when regenerated from defaults.
system={[".name"]="cfg0a",[".type"]="system"}
assert(mon.snapshot().aott_metrics=="0")
print("VENDOR_LUCI_UCI_MONITORING_OFFLINE_PASS")
