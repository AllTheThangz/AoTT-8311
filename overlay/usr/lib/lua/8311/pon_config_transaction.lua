-- AoTT-8311 V3 guarded PON/OMCI configuration transaction.
-- Sensitive request values remain in the private job request only. Public
-- results contain fixed statuses and booleans, never subscriber values.
local nixio=require "nixio"
local fs=require "nixio.fs"
local environment=require "8311.pon_environment"
local recovery=require "8311.pon_config_recovery"
local pon_uci=require "8311.pon_config_uci"
local pon_mib=require "8311.pon_mib_runtime"
local runtime=require "8311.pon_config_runtime"
local web=require "8311.webutil"
local mib_profile=require "8311.mib_profile"
local M={}
local VERIFY_TICKS=60
local WAIT_TICKS=90

local function valid_job(id)
    return type(id)=="string" and #id==32 and not id:find("[^0-9a-f]")
end
local function allowed(root,jobdir,mode)
    if mode=="production_runtime" then
        local id=type(jobdir)=="string" and
            jobdir:match("^/tmp/8311%-web%-jobs/([0-9a-f]+)$")
        return root=="" and valid_job(id),id
    end
    local suffix=type(root)=="string" and
        root:match("^/var/tmp/aott%-pon%-transaction%-test%-([0-9a-f]+)$")
    if mode=="offline_synthetic" and suffix and #suffix==16 and
       jobdir==root.."/job" then return true,string.rep("b",32) end
    return false,nil
end
local function safe(fn,...)
    local ok,a,b=pcall(fn,...)
    if not ok then return nil,"pon_transaction_provider_error" end
    return a,b
end
local function provider_ok(p)
    for _,name in ipairs({
        "pending","snapshot","plan","arm","apply_environment","apply_uci",
        "apply_mib","apply_aux","restart","verify","confirmed","clear",
        "restore","sleep",
    }) do
        if type(p)~="table" or type(p[name])~="function" then return false end
    end
    return true
end

local function rollback(provider,jobid,reason)
    local restored,why=safe(provider.restore,jobid,true)
    if not restored then
        return nil,"pon_rollback_failed:"..tostring(why or reason)
    end
    return {
        schema=1,status="PON_TRANSACTION_ROLLED_BACK",
        rollback_verified=true,confirmation_required=false,
        pon_registered_o5_1=restored.pon_registered_o5_1==true,
        olt_per_field_effect_proven=false,
        contains_configuration_values=false,failure_reason=reason,
    }
end

local function transaction(root,jobdir,changes,mode,provider,wait_ticks,verify_ticks)
    local scoped,jobid=allowed(root,jobdir,mode)
    if not scoped or not provider_ok(provider) then
        return nil,"pon_transaction_scope_refused"
    end
    local pending,why=safe(provider.pending)
    if not pending then return nil,why end
    if pending.pending==true then return nil,"pon_transaction_already_pending" end

    local snapshot,snapshot_why=safe(provider.snapshot)
    if not snapshot then return nil,snapshot_why or "pon_snapshot_failed" end
    local plan,plan_why=safe(provider.plan,snapshot,changes)
    if not plan then return nil,plan_why or "pon_plan_failed" end
    if plan.changes_required==false then
        local verified,verify_why=safe(provider.verify,plan)
        if not verified then return nil,verify_why or "pon_noop_runtime_mismatch" end
        return {
            schema=1,status="PON_TRANSACTION_NO_CHANGE",
            confirmation_required=false,local_runtime_verified=true,
            pon_registered_o5_1=true,olt_per_field_effect_proven=false,
            contains_configuration_values=false,
        }
    end

    local armed,arm_why=safe(provider.arm,jobid,snapshot)
    if not armed then return nil,arm_why or "pon_recovery_arm_failed" end
    local e,ewhy=safe(provider.apply_environment,snapshot,plan)
    if not e then return rollback(provider,jobid,ewhy or "pon_environment_apply_failed") end
    local u,uwhy=safe(provider.apply_uci,plan)
    if not u then return rollback(provider,jobid,uwhy or "pon_uci_apply_failed") end
    local m,mwhy=safe(provider.apply_mib,plan)
    if not m then return rollback(provider,jobid,mwhy or "pon_mib_apply_failed") end
    local a,awhy=safe(provider.apply_aux,plan)
    if not a then return rollback(provider,jobid,awhy or "pon_aux_apply_failed") end
    local restarted,rwhy=safe(provider.restart)
    if not restarted then return rollback(provider,jobid,rwhy or "omcid_restart_failed") end

    local verified,verify_why
    for attempt=1,verify_ticks do
        verified,verify_why=safe(provider.verify,plan)
        if verified then break end
        if attempt<verify_ticks then provider.sleep() end
    end
    if not verified then
        return rollback(provider,jobid,verify_why or "pon_runtime_convergence_failed")
    end
    local phase,phase_why=safe(provider.phase,jobid,"trial_running")
    if not phase then return rollback(provider,jobid,phase_why or "pon_trial_phase_failed") end

    for _=1,wait_ticks do
        local confirmed,confirm_why=safe(provider.confirmed,jobid)
        if confirmed==nil then
            return rollback(provider,jobid,confirm_why or "pon_confirmation_state_failed")
        end
        if confirmed==true then
            local cleared,clear_why=safe(provider.clear,jobid)
            if not cleared then return nil,clear_why or "pon_recovery_cleanup_failed" end
            return {
                schema=1,status="PON_TRANSACTION_CONFIRMED",
                confirmation_required=false,local_runtime_verified=true,
                pon_registered_o5_1=true,rollback_verified=false,
                olt_per_field_effect_proven=false,
                contains_configuration_values=false,
            }
        end
        provider.sleep()
    end
    return rollback(provider,jobid,"pon_confirmation_timeout")
end

local function restart_omcid()
    local code,_,overflow=web.capture({"/etc/init.d/omcid.sh","stop"},4096)
    if code~=0 or overflow then return nil,"omcid_stop_failed" end
    code,_,overflow=web.capture({"/etc/init.d/omcid.sh","start"},4096)
    if code~=0 or overflow then return nil,"omcid_start_failed" end
    return true
end

local function production_provider()
    local P={}
    function P.pending() return recovery.pending() end
    function P.snapshot()
        local env_raw,records=environment.snapshot()
        if not env_raw then return nil,records end
        local raw,why=pon_uci.snapshot()
        if not raw then return nil,why end
        return {environment=env_raw,records=records,raw=raw}
    end
    function P.plan(snapshot,changes)
        if type(snapshot)~="table" or type(snapshot.environment)~="string" or
           type(snapshot.raw)~="table" then return nil,"pon_snapshot_invalid" end
        local desired,why=environment.request(snapshot.environment,changes)
        if not desired then return nil,why end
        local records,decode_why=environment.decode(desired)
        if not records then return nil,decode_why end
        local proposed,changed={}, {__pon_transaction=true}
        for _,id in ipairs(environment.fields) do
            local row=records[id]
            proposed[id]=row and row.state=="value" and row.value or ""
        end
        for id in pairs(changes) do changed[id]=true end
        local selected=proposed.mib_file~="" and proposed.mib_file or "/etc/mibs/prx300_1U.ini"
        local profile,profile_why=mib_profile.inspect(selected)
        if not profile then return nil,"pon_mib_profile_inspection_failed:"..tostring(profile_why) end
        local compatible,profile_errors=mib_profile.validate_for_configuration(profile,proposed,changed)
        if not compatible then
            local field=next(profile_errors or {})
            return nil,"pon_mib_profile_incompatible_"..tostring(field or "unknown")
        end
        return {
            desired_environment=desired,records=records,changes=changes,
            changes_required=desired~=snapshot.environment,
        }
    end
    function P.arm(jobid,snapshot)
        return recovery.arm(jobid,snapshot.environment,
            snapshot.raw.gpon,snapshot.raw.omci,snapshot.raw.network)
    end
    function P.apply_environment(snapshot,plan)
        local receipt,desired=environment.apply_request(snapshot.environment,plan.changes)
        if not receipt then return nil,desired end
        if desired~=plan.desired_environment then return nil,"pon_environment_plan_drift" end
        return true
    end
    function P.apply_uci(plan)
        local receipt,why=pon_uci.apply(plan.records)
        return receipt and true or nil,why
    end
    function P.apply_mib(plan)
        local receipt,why=pon_mib.apply(plan.records)
        return receipt and true or nil,why
    end
    function P.apply_aux(plan)
        return runtime.apply_aux(plan.records)
    end
    P.restart=restart_omcid
    function P.verify(plan)
        return runtime.local_verify(plan.records)
    end
    function P.phase(jobid,phase) return recovery.phase(jobid,phase) end
    function P.confirmed(jobid) return recovery.confirmed(jobid) end
    function P.clear(jobid) return recovery.clear(jobid) end
    function P.restore(jobid,do_restart)
        local backups,why=recovery.load(jobid)
        if not backups then return nil,why end
        if do_restart then
            local code,_,overflow=web.capture({"/etc/init.d/omcid.sh","stop"},4096)
            if code~=0 or overflow then return nil,"omcid_stop_before_restore_failed" end
        end
        local u,uwhy=pon_uci.restore()
        if not u then return nil,uwhy end
        local m,mwhy=recovery.restore_mibs(jobid)
        if not m then return nil,mwhy end
        local e,ewhy=environment.restore(backups.environment)
        if not e then return nil,ewhy end
        local records,decode_why=environment.decode(backups.environment)
        if not records then return nil,decode_why end
        local a,awhy=runtime.apply_aux(records)
        if not a then return nil,awhy end
        if do_restart then
            local r,rwhy=restart_omcid()
            if not r then return nil,rwhy end
            local verified,verify_why
            for attempt=1,VERIFY_TICKS do
                verified,verify_why=runtime.local_verify(records)
                if verified then break end
                if attempt<VERIFY_TICKS then nixio.nanosleep(2,0) end
            end
            if not verified then return nil,verify_why or "pon_restore_runtime_verification_failed" end
        end
        local cleared,clear_why=recovery.clear(jobid)
        if not cleared then return nil,clear_why end
        return {
            status="PON_CONFIGURATION_RESTORED",
            pon_registered_o5_1=do_restart and true or false,
            contains_configuration_values=false,
        }
    end
    function P.sleep() nixio.nanosleep(2,0) end
    return P
end

function M.apply(jobdir,changes)
    return transaction("",jobdir,changes,"production_runtime",
        production_provider(),WAIT_TICKS,VERIFY_TICKS)
end
function M.pending() return recovery.pending() end
function M.confirm(jobid) return recovery.confirm(jobid) end
function M.recover_pending()
    local state,why=recovery.pending()
    if not state then return nil,why end
    if state.pending~=true then return {status="NO_PENDING_PON_TRANSACTION",recovered=false} end
    local confirmed,confirm_why=recovery.confirmed(state.job_id)
    if confirmed==nil then return nil,confirm_why end
    if confirmed==true then
        local cleared,clear_why=recovery.clear(state.job_id)
        if not cleared then return nil,clear_why end
        return {
            status="CONFIRMED_PON_TRANSACTION_RECOVERY_CLEANUP",
            recovered=false,confirmed_preserved=true,
            contains_configuration_values=false,
        }
    end
    local restored,restore_why=production_provider().restore(state.job_id,false)
    if not restored then return nil,restore_why end
    return {
        status="PENDING_PON_TRANSACTION_RECOVERED",recovered=true,
        confirmed_preserved=false,
        contains_configuration_values=false,
    }
end
function M.fixture_transaction(root,jobdir,changes,provider,wait_ticks,verify_ticks)
    return transaction(root,jobdir,changes,"offline_synthetic",provider,
        wait_ticks or 1,verify_ticks or 2)
end
M.WAIT_SECONDS=WAIT_TICKS*2
M.VERIFY_SECONDS=VERIFY_TICKS*2
return M
