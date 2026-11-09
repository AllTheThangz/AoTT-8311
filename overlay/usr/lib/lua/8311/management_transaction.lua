-- AoTT-8311 V3 guarded management configuration transaction.
-- Applies one complete management tuple with persistent rollback and explicit
-- post-change confirmation. Public results never contain address/MAC/DNS values.
local nixio=require "nixio"
local fs=require "nixio.fs"
local web=require "8311.webutil"
local transition=require "8311.vlan_transition"
local environment=require "8311.management_environment"
local management_uci=require "8311.management_uci"
local recovery=require "8311.management_recovery_store"
local runtime=require "8311.management_runtime"
local access=require "8311.management_access"

local M={}
local WAIT_TICKS=150
local VERIFY_TICKS=10
local ROOT="/ptconf/8311/aott-recovery/v1"
local NETWORK_BACKUP=ROOT.."/management/network.before"
local FIREWALL_BACKUP=ROOT.."/management/firewall.before"
local DROPBEAR_BACKUP=ROOT.."/management/dropbear.before"

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
        root:match("^/var/tmp/aott%-management%-transaction%-test%-([0-9a-f]+)$")
    if mode=="offline_synthetic" and suffix and #suffix==16 and
       jobdir==root.."/job" then
        return true,string.rep("a",32)
    end
    return false,nil
end

local function provider_ok(p)
    local names={
        "pending","snapshot","plan","arm","apply_environment","apply_uci",
        "apply_access","reload","verify","confirmed","clear","restore","sleep"
    }
    if type(p)~="table" then return false end
    for _,name in ipairs(names) do
        if type(p[name])~="function" then return false end
    end
    return true
end

local function safe_call(fn,...)
    local ok,a,b=pcall(fn,...)
    if not ok then return nil,"management_transaction_provider_error" end
    return a,b
end

local function rollback(provider,jobid,reason)
    local restored,why=safe_call(provider.restore,jobid,true)
    if not restored then
        return nil,"management_rollback_failed:"..tostring(why or reason)
    end
    return {
        schema=1,status="MANAGEMENT_TRANSACTION_ROLLED_BACK",
        rollback_verified=true,confirmation_required=false,
        contains_configuration_values=false,failure_reason=reason
    }
end

local function transaction(root,jobdir,request,mode,provider,wait_ticks,verify_ticks)
    local ok,jobid=allowed(root,jobdir,mode)
    if not ok or not provider_ok(provider) then
        return nil,"management_transaction_scope_refused"
    end
    local pending,why=safe_call(provider.pending)
    if not pending then return nil,why end
    if pending.pending==true then return nil,"management_transaction_already_pending" end

    local snapshot,snapshot_why=safe_call(provider.snapshot)
    if not snapshot then return nil,snapshot_why or "management_snapshot_failed" end

    local plan,plan_why=safe_call(provider.plan,snapshot,request)
    if not plan then return nil,plan_why or "management_plan_failed" end
    if plan.changes_required==false then
        local verified,verify_why=safe_call(provider.verify,request)
        if not verified then return nil,verify_why or "management_noop_runtime_mismatch" end
        return {
            schema=1,status="MANAGEMENT_TRANSACTION_NO_CHANGE",
            confirmation_required=false,runtime_verified=true,
            contains_configuration_values=false
        }
    end

    local armed,arm_why=safe_call(provider.arm,jobid,snapshot)
    if not armed then return nil,arm_why or "management_recovery_arm_failed" end

    local env_ok,env_why=safe_call(provider.apply_environment,snapshot,request)
    if not env_ok then return rollback(provider,jobid,
        env_why or "management_environment_apply_failed") end

    local uci_ok,uci_why=safe_call(provider.apply_uci,plan)
    if not uci_ok then return rollback(provider,jobid,
        uci_why or "management_uci_apply_failed") end

    local access_ok,access_why=safe_call(provider.apply_access,snapshot,request)
    if not access_ok then return rollback(provider,jobid,
        access_why or "management_access_apply_failed") end

    local reload_ok,reload_why=safe_call(provider.reload)
    if not reload_ok then return rollback(provider,jobid,
        reload_why or "management_reload_failed") end

    local verified,verify_why
    for attempt=1,verify_ticks do
        verified,verify_why=safe_call(provider.verify,request)
        if verified then break end
        if attempt<verify_ticks then provider.sleep() end
    end
    if not verified then return rollback(provider,jobid,
        verify_why or "management_runtime_convergence_failed") end

    for _=1,wait_ticks do
        local confirmed,confirm_why=safe_call(provider.confirmed,jobid)
        if confirmed==nil then
            return rollback(provider,jobid,
                confirm_why or "management_confirmation_state_failed")
        end
        if confirmed==true then
            local cleared,clear_why=safe_call(provider.clear,jobid)
            if not cleared then
                return nil,clear_why or "management_recovery_cleanup_failed"
            end
            return {
                schema=1,status="MANAGEMENT_TRANSACTION_CONFIRMED",
                confirmation_required=false,runtime_verified=true,
                rollback_verified=false,contains_configuration_values=false
            }
        end
        provider.sleep()
    end
    return rollback(provider,jobid,"management_confirmation_timeout")
end

local function production_reload()
    local code,_,overflow=web.capture({"/etc/init.d/network","reload"},4096)
    if code~=0 or overflow then return nil,"network_reload_failed" end
    code,_,overflow=web.capture({"/etc/init.d/firewall","reload"},4096)
    if code~=0 or overflow then return nil,"firewall_reload_failed" end
    local ssh,ssh_why=access.reload()
    if not ssh then return nil,ssh_why end
    return true
end

local function production_provider()
    local P={}

    function P.pending()
        return recovery.pending("","production_runtime")
    end

    function P.snapshot()
        local uci_snapshot,raw=management_uci.snapshot()
        if not uci_snapshot then return nil,raw end
        local env_raw,records=environment.snapshot()
        if not env_raw then return nil,records end
        local access_snapshot,access_why=access.snapshot()
        if not access_snapshot then return nil,access_why end
        return {uci=uci_snapshot,raw=raw,environment=env_raw,
                access=access_snapshot}
    end

    function P.plan(snapshot,request)
        if type(snapshot)~="table" or type(snapshot.uci)~="table" then
            return nil,"management_snapshot_invalid"
        end
        local handle,why=transition.prepare_management(
            snapshot.uci,request,"eth0_0_1_lct","lan")
        if not handle then return nil,why end
        local summary,summary_why=transition.redacted_summary(
            handle,"production_preview")
        if not summary then return nil,summary_why end
        local desired_environment,env_why=environment.request(
            snapshot.environment,request)
        if not desired_environment then return nil,env_why end
        return {
            handle=handle,summary=summary,
            environment_changed=desired_environment~=snapshot.environment,
            changes_required=summary.changes_required or
                desired_environment~=snapshot.environment
        }
    end

    function P.arm(jobid,snapshot)
        if type(snapshot)~="table" or type(snapshot.raw)~="table" or
           type(snapshot.raw.network)~="string" or
           type(snapshot.raw.firewall)~="string" or
           type(snapshot.environment)~="string" or
           type(snapshot.access)~="table" or
           type(snapshot.access.raw)~="string" then
            return nil,"management_recovery_snapshot_invalid"
        end
        return recovery.arm("",jobid,snapshot.raw.network,
            snapshot.raw.firewall,snapshot.environment,snapshot.access.raw,
            "production_runtime")
    end

    function P.apply_environment(snapshot,request)
        local receipt,desired=environment.apply_request(snapshot.environment,request)
        if not receipt then return nil,desired end
        return true
    end

    function P.apply_uci(plan)
        if type(plan)~="table" or not plan.handle then
            return nil,"management_plan_handle_missing"
        end
        local receipt,why=management_uci.apply(plan.handle)
        if not receipt then return nil,why end
        return true
    end

    function P.apply_access(snapshot,request)
        if type(snapshot)~="table" or type(snapshot.access)~="table" or
           type(request)~="table" then
            return nil,"management_access_request_invalid"
        end
        local receipt,why=access.apply(snapshot.access,request.vlan)
        if not receipt then return nil,why end
        return true
    end

    P.reload=production_reload

    function P.verify(request)
        local record,why=runtime.live(request)
        if not record then return nil,why end
        local ssh,ssh_why=access.verify(request.vlan)
        if not ssh then return nil,ssh_why end
        return {status="MANAGEMENT_RUNTIME_AND_SSH_VERIFIED",
                contains_configuration_values=false}
    end

    function P.confirmed(jobid)
        return recovery.confirmed("",jobid,"production_runtime")
    end

    function P.clear(jobid)
        return recovery.clear("",jobid,"production_runtime")
    end

    function P.restore(jobid,do_reload)
        local backups,why=recovery.load("",jobid,"production_runtime")
        if not backups then return nil,why end
        local a,awhy=management_uci.import_raw("network",NETWORK_BACKUP)
        if not a then return nil,awhy end
        local b,bwhy=management_uci.import_raw("firewall",FIREWALL_BACKUP)
        if not b then return nil,bwhy end
        local d,dwhy=access.import_raw(DROPBEAR_BACKUP)
        if not d then return nil,dwhy end
        local e,ewhy=environment.restore(backups.environment)
        if not e then return nil,ewhy end
        if do_reload then
            local r,rwhy=production_reload()
            if not r then return nil,rwhy end
        end
        local request,request_why=environment.request_from_snapshot(
            backups.environment)
        if not request then return nil,request_why end
        if do_reload then
            local verified,verify_why
            for attempt=1,VERIFY_TICKS do
                verified,verify_why=runtime.live(request)
                if verified then
                    local ssh,ssh_why=access.verify(request.vlan)
                    if ssh then break end
                    verified=nil
                    verify_why=ssh_why
                end
                if attempt<VERIFY_TICKS then nixio.nanosleep(1,0) end
            end
            if not verified then return nil,verify_why or
                "management_restore_runtime_verification_failed" end
        end
        local cleared,clear_why=recovery.clear("",jobid,"production_runtime")
        if not cleared then return nil,clear_why end
        return {status="MANAGEMENT_RESTORED",runtime_verified=do_reload,
                contains_configuration_values=false}
    end

    function P.sleep()
        nixio.nanosleep(2,0)
    end

    return P
end

function M.apply(jobdir,request)
    return transaction("",jobdir,request,"production_runtime",
        production_provider(),WAIT_TICKS,VERIFY_TICKS)
end

function M.pending()
    return recovery.pending("","production_runtime")
end

function M.confirm(jobid)
    return recovery.confirm("",jobid,"production_runtime")
end

function M.recover_pending()
    local state,why=recovery.pending("","production_runtime")
    if not state then return nil,why end
    if state.pending~=true then
        return {status="NO_PENDING_MANAGEMENT_TRANSACTION",recovered=false}
    end
    local restored,restore_why=production_provider().restore(
        state.job_id,false)
    if not restored then return nil,restore_why end
    return {status="PENDING_MANAGEMENT_TRANSACTION_RECOVERED",
            recovered=true,contains_configuration_values=false}
end

function M.fixture_transaction(root,jobdir,request,provider,wait_ticks,verify_ticks)
    return transaction(root,jobdir,request,"offline_synthetic",provider,
        wait_ticks or 1,verify_ticks or 2)
end

M.WAIT_SECONDS=WAIT_TICKS*2
M.VERIFY_SECONDS=VERIFY_TICKS
return M
