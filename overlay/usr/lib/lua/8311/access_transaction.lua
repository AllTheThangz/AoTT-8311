-- AoTT-8311 V3 guarded access/server transaction.
local nixio=require "nixio"
local config=require "8311.access_config"
local uci=require "8311.access_uci"
local runtime=require "8311.access_runtime"
local recovery=require "8311.access_recovery_store"
local web=require "8311.webutil"
local M={}

local WAIT_TICKS=90
local VERIFY_TICKS=10

local function valid_job(id)
    return type(id)=="string" and #id==32 and not id:find("[^0-9a-f]")
end
local function job_id(jobdir)
    local id=type(jobdir)=="string" and jobdir:match("^/tmp/8311%-web%-jobs/([0-9a-f]+)$")
    return valid_job(id) and id or nil
end
local function reload(snapshot)
    if type(snapshot)~="table" or type(snapshot.values)~="table" then
        return nil,"access_reload_snapshot_invalid"
    end
    local code,_,overflow=web.capture({"/etc/init.d/dropbear","stop"},4096)
    if code~=0 or overflow then return nil,"dropbear_stop_failed" end
    if snapshot.values.ssh_enabled=="1" then
        code,_,overflow=web.capture({"/etc/init.d/dropbear","start"},4096)
        if code~=0 or overflow then return nil,"dropbear_start_failed" end
    end
    code,_,overflow=web.capture({"/etc/init.d/uhttpd","stop"},4096)
    if code~=0 or overflow then return nil,"uhttpd_stop_failed" end
    code,_,overflow=web.capture({"/etc/init.d/uhttpd","start"},4096)
    if code~=0 or overflow then return nil,"uhttpd_start_failed" end
    code,_,overflow=web.capture({"/etc/init.d/firewall","restart"},8192)
    if code~=0 or overflow then return nil,"firewall_restart_failed" end
    return true
end
local function convergence(snapshot)
    local why
    for attempt=1,VERIFY_TICKS do
        local ok
        ok,why=runtime.verify(snapshot)
        if ok then return ok end
        if attempt<VERIFY_TICKS then nixio.nanosleep(1,0) end
    end
    return nil,why or "access_runtime_convergence_failed"
end
local function restore(job,do_reload)
    local backup,why=recovery.load(job)
    if not backup then return nil,why end
    local ok,restore_why=uci.restore_all()
    if not ok then return nil,restore_why end
    local snapshot,snapshot_why=config.snapshot()
    if not snapshot then return nil,snapshot_why end
    if do_reload then
        local r,rwhy=reload(snapshot);if not r then return nil,rwhy end
        local verified,vwhy=convergence(snapshot);if not verified then return nil,vwhy end
    end
    local cleared,clear_why=recovery.clear(job)
    if not cleared then return nil,clear_why end
    return {status="ACCESS_TRANSACTION_RESTORED",runtime_verified=do_reload,
            contains_configuration_values=false}
end
local function rollback(job,reason)
    local restored,why=restore(job,true)
    if not restored then return nil,"access_rollback_failed:"..tostring(why or reason) end
    return {
        schema=1,status="ACCESS_TRANSACTION_ROLLED_BACK",
        rollback_verified=true,confirmation_required=false,
        contains_configuration_values=false,failure_reason=reason,
    }
end

function M.apply(jobdir,request)
    local job=job_id(jobdir)
    if not job then return nil,"access_transaction_scope_refused" end
    local clean=config.request_ok(request)
    if not clean then return nil,"access_transaction_request_invalid" end
    local pending,why=recovery.pending()
    if not pending then return nil,why end
    if pending.pending==true then return nil,"access_transaction_already_pending" end

    local before,bwhy=config.snapshot()
    if not before then return nil,bwhy end
    if before.revision~=clean.revision then return nil,"access_configuration_changed" end
    local prepared,errors,status=config.prepare(before,clean)
    if not prepared then return nil,"access_preview_failed_"..tostring(status or errors and errors.request or "invalid") end
    if not prepared.changes_required then
        local verified,vwhy=runtime.verify(before)
        if not verified then return nil,vwhy end
        return {schema=1,status="ACCESS_TRANSACTION_NO_CHANGE",
                confirmation_required=false,runtime_verified=true,
                contains_configuration_values=false}
    end

    local raw,raw_why=uci.raw_snapshot()
    if not raw then return nil,raw_why end
    local armed,arm_why=recovery.arm(job,raw)
    if not armed then return nil,arm_why end

    local receipt,after_or_why=uci.apply(before,prepared.desired)
    if not receipt then return rollback(job,after_or_why or "access_uci_apply_failed") end
    local after=after_or_why
    local loaded,load_why=reload(after)
    if not loaded then return rollback(job,load_why or "access_service_reload_failed") end
    local verified,verify_why=convergence(after)
    if not verified then return rollback(job,verify_why or "access_runtime_convergence_failed") end

    for _=1,WAIT_TICKS do
        local confirmed,confirm_why=recovery.confirmed(job)
        if confirmed==nil then return rollback(job,confirm_why or "access_confirmation_state_failed") end
        if confirmed==true then
            local cleared,clear_why=recovery.clear(job)
            if not cleared then return nil,clear_why end
            return {
                schema=1,status="ACCESS_TRANSACTION_CONFIRMED",
                confirmation_required=false,runtime_verified=true,
                rollback_verified=false,contains_configuration_values=false,
            }
        end
        nixio.nanosleep(2,0)
    end
    return rollback(job,"access_confirmation_timeout")
end

function M.pending()
    return recovery.pending()
end
function M.confirm(job)
    return recovery.confirm(job)
end
function M.recover_pending()
    local pending,why=recovery.pending()
    if not pending then return nil,why end
    if pending.pending~=true then return {status="NO_PENDING_ACCESS_TRANSACTION",recovered=false} end
    local restored,restore_why=restore(pending.job_id,false)
    if not restored then return nil,restore_why end
    return {status="PENDING_ACCESS_TRANSACTION_RECOVERED",
            recovered=true,contains_configuration_values=false}
end

M.WAIT_SECONDS=WAIT_TICKS*2
return M
