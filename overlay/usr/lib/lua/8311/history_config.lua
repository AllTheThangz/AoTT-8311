-- AoTT-8311 V3 local-history configuration.
-- Dedicated UCI package; history data remains RAM-only in this revision.
local uci_lib=require "luci.model.uci"
local web=require "8311.webutil"
local fs=require "nixio.fs"
local lock=require "8311.history_process_lock"
local M={}
local DEFAULT={
    enabled="0",pon_interval_seconds="60",host_interval_seconds="60",
    ram_sample_limit="120",ram_event_limit="128",
}
local KEYS={"enabled","pon_interval_seconds","host_interval_seconds",
            "ram_sample_limit","ram_event_limit"}
local PON={["60"]=true,["120"]=true,["300"]=true}
local HOST={["30"]=true,["60"]=true,["120"]=true,["300"]=true}
local function raw(u)
    local section=u:get_all("aott_history","main")
    local out={}
    for _,key in ipairs(KEYS) do
        local value=type(section)=="table" and section[key] or nil
        out[key]=type(value)=="string" and value or DEFAULT[key]
    end
    return out
end
local function revision(values)
    local parts={}
    for _,key in ipairs(KEYS) do parts[#parts+1]=key.."="..values[key] end
    return web.digest_text(table.concat(parts,"\n"))
end
local function running()
    if not fs.stat(lock.PRODUCTION_DIR) then return false,"not_started" end
    local state,why=lock.writer_present(lock.PRODUCTION_DIR)
    if state==true then return true,why end
    if state==false then return false,why end
    return nil,why
end
function M.snapshot(u)
    u=u or uci_lib.cursor()
    local values=raw(u)
    local rev,why=revision(values)
    if not rev then return nil,why end
    local active,status=running()
    return {
        schema=1,revision=rev,enabled=values.enabled,
        pon_interval_seconds=values.pon_interval_seconds,
        host_interval_seconds=values.host_interval_seconds,
        ram_sample_limit=values.ram_sample_limit,
        ram_event_limit=values.ram_event_limit,
        service_running=active,service_status=status,
        persistence_available=false,persistent_history_enabled=false,
        remote_notifications=false,actual_isp_uptime_unverified=true,
    }
end
function M.validate(form)
    if type(form)~="table" then return nil,"Invalid history request" end
    local allowed={revision=true}
    for _,key in ipairs(KEYS) do allowed[key]=true end
    for key,value in pairs(form) do
        if not allowed[key] or type(value)~="string" then
            return nil,"Unknown or duplicate history field"
        end
    end
    if type(form.revision)~="string" or #form.revision~=64 or
       form.revision:find("[^0-9a-f]") then
        return nil,"Refresh history settings before saving"
    end
    if form.enabled~="0" and form.enabled~="1" then
        return nil,"Invalid history enabled value"
    end
    if not PON[form.pon_interval_seconds] then return nil,"Invalid PON sampling interval" end
    if not HOST[form.host_interval_seconds] then return nil,"Invalid host sampling interval" end
    local samples=tonumber(form.ram_sample_limit)
    local events=tonumber(form.ram_event_limit)
    if not samples or samples~=math.floor(samples) or samples<30 or samples>720 then
        return nil,"RAM sample limit must be 30 through 720"
    end
    if not events or events~=math.floor(events) or events<16 or events>256 then
        return nil,"RAM event limit must be 16 through 256"
    end
    return {
        enabled=form.enabled,pon_interval_seconds=form.pon_interval_seconds,
        host_interval_seconds=form.host_interval_seconds,
        ram_sample_limit=tostring(samples),ram_event_limit=tostring(events),
    }
end
local function set_values(u,values)
    if not u:set("aott_history","main","history") then return nil end
    for _,key in ipairs(KEYS) do
        if not u:set("aott_history","main",key,values[key]) then return nil end
    end
    return u:commit("aott_history")
end
local function service(argv)
    local code,_,overflow=web.capture(argv,1024)
    return code==0 and overflow==false
end
local function apply_service(enabled)
    if enabled=="1" then
        if not service({"/etc/init.d/8311-history","enable"}) then return nil end
        if not service({"/etc/init.d/8311-history","restart"}) then
            service({"/etc/init.d/8311-history","disable"})
            return nil
        end
        return true
    end
    local stopped=service({"/etc/init.d/8311-history","stop"})
    local disabled=service({"/etc/init.d/8311-history","disable"})
    return stopped and disabled
end
local function equal_settings(a,b)
    if type(a)~="table" or type(b)~="table" then return false end
    for _,key in ipairs(KEYS) do
        if a[key]~=b[key] then return false end
    end
    return true
end

local function verified_readback(target,require_explicit)
    local opened,u=pcall(uci_lib.cursor)
    if not opened or not u then
        return nil,"history_saved_readback_unavailable"
    end
    -- The history page supplies defaults when a UCI key is missing.
    -- That is fine for viewing but cannot establish committed write
    -- success. Verify the exact persisted keys, not the fallback values.
    if require_explicit then
        local read_ok,section=pcall(u.get_all,u,"aott_history","main")
        if not read_ok or not equal_settings(section,target) then
            return nil,"history_saved_readback_mismatch"
        end
    end
    local ok,state=pcall(M.snapshot,u)
    if not ok or type(state)~="table" or
       not equal_settings(state,target) then
        return nil,"history_saved_readback_mismatch"
    end
    -- The enabled flag is only a stored setting. Require the independently
    -- held worker lock to agree before reporting activation as successful.
    if target.enabled=="1" and state.service_running~=true then
        return nil,"history_worker_not_verified_running"
    end
    if target.enabled=="0" and state.service_running~=false then
        return nil,"history_worker_not_verified_stopped"
    end
    return state
end

-- Does not promise a clean rollback based on UCI commit or init.d exit
-- status alone. The old settings and worker state must both be read back.
local function restore(old)
    local created,u=pcall(uci_lib.cursor)
    if not created or not u then return false end
    local saved,committed=pcall(set_values,u,old)
    if not saved or not committed then return false end
    local invoked,started=pcall(apply_service,old.enabled)
    if not invoked or not started then return false end
    local state=verified_readback(old,true)
    return state~=nil
end

function M.apply(form)
    local values,why=M.validate(form)
    if not values then return nil,why,422 end
    local guard=web.lock("/tmp/8311-history-config.lock")
    if not guard then return nil,"History settings are busy; retry",409 end
    local function finish(a,b,c) guard:close(); return a,b,c end
    local created,u=pcall(uci_lib.cursor)
    if not created or not u then
        return finish(nil,"History configuration read unavailable",503)
    end
    local ok,before=pcall(M.snapshot,u)
    if not ok or type(before)~="table" then
        return finish(nil,"History settings are unavailable",503)
    end
    if form.revision~=before.revision then
        return finish(nil,"History settings changed; refresh before saving",409)
    end
    local old=raw(u)
    if equal_settings(old,values) then
        -- No service call, no new UCI commit and no unnecessary flash writes.
        local current=verified_readback(old)
        if not current then
            return finish(nil,"History worker state is not verified; no settings changed",503)
        end
        return finish(current,nil,200)
    end
    local wrote,saved=pcall(set_values,u,values)
    if not wrote or not saved then
        local restored=restore(old)
        return finish(nil,restored and
            "History write failed; previous settings restored and verified" or
            "History write failed; rollback unverified, inspect saved and running settings",503)
    end
    local invoked,service_ok=pcall(apply_service,values.enabled)
    local after=nil
    if invoked and service_ok then after=verified_readback(values,true) end
    if not after then
        local restored=restore(old)
        return finish(nil,restored and
            "History activation/readback failed; previous settings restored and verified" or
            "History activation/readback failed; rollback unverified, inspect saved and running settings",503)
    end
    return finish(after,nil,200)
end
function M.runtime()
    local state=M.snapshot()
    if not state then return nil,"history_config_unavailable" end
    if state.enabled~="1" then return nil,"history_disabled" end
    return {
        pon_interval_seconds=tonumber(state.pon_interval_seconds),
        host_interval_seconds=tonumber(state.host_interval_seconds),
        ram_sample_limit=tonumber(state.ram_sample_limit),
        ram_event_limit=tonumber(state.ram_event_limit),
    }
end
return M
