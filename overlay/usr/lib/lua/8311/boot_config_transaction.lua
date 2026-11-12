-- AoTT-8311 V3 guarded one-boot transaction for boot-time settings.
-- Candidate values are persistent only until explicitly confirmed. A watchdog
-- restores the prior environment and bootcmd then reboots on timeout.
local nixio=require "nixio"
local fs=require "nixio.fs"
local tools=require "8311.tools"
local store=require "8311.boot_config_store"
local M={}
local FIELDS={
    bootdelay={base=true},
    uart_select={base=true},
    failsafe_delay={base=false},
    persist_root={base=false},
}

local function valid(id,value)
    if id=="bootdelay" then return type(value)=="string" and value:match("^[0-3]$")~=nil end
    if id=="uart_select" then return value=="on" or value=="off" end
    if id=="failsafe_delay" then
        return type(value)=="string" and value:match("^%d+$")~=nil and
            tonumber(value)>=0 and tonumber(value)<=300 and tostring(tonumber(value))==value
    end
    if id=="persist_root" then return value=="0" or value=="1" end
    return false
end

local function boot_id()
    local value=fs.readfile("/proc/sys/kernel/random/boot_id",80)
    if type(value)~="string" then return nil end
    value=value:gsub("[\r\n]+$","")
    if #value~=36 or value:find("[^0-9a-f-]") then return nil end
    return value
end

local function env_key(id)
    return FIELDS[id].base and id or "8311_"..id
end

local function snapshot(ids)
    local values,why=tools.fwenv_read_all()
    if not values then return nil,why end
    local out={}
    for _,id in ipairs(ids) do
        local key=env_key(id)
        out[id]=values[key]~=nil and {present=true,value=values[key]} or {present=false}
    end
    local bootcmd=values.bootcmd~=nil and {present=true,value=values.bootcmd} or {present=false}
    return out,bootcmd
end

local function set_record(id,row)
    if not FIELDS[id] or type(row)~="table" then return false end
    local setter=FIELDS[id].base and tools.fw_setenv or tools.fw_setenv_8311
    -- Setters may modify persistent environment before throwing. The
    -- prepared recovery plan must remain available until restoration has
    -- independently passed readback.
    local ok,wrote=pcall(setter,{id,row.present and row.value or nil})
    return ok and wrote==true
end

local function set_bootcmd(row)
    if type(row)~="table" then return false end
    local ok,wrote=pcall(tools.fw_setenv,{"bootcmd",row.present and row.value or nil})
    return ok and wrote==true
end

local function equal_record(values,id,row)
    local value=values[env_key(id)]
    if row.present then return value==row.value end
    return value==nil or value==""
end

local function verify(records,bootcmd)
    local ok,values=pcall(tools.fwenv_read_all)
    if not ok or type(values)~="table" then return false end
    for id,row in pairs(records) do
        if not equal_record(values,id,row) then return false end
    end
    if bootcmd then
        if bootcmd.present then
            if values.bootcmd~=bootcmd.value then return false end
        elseif values.bootcmd~=nil and values.bootcmd~="" then
            return false
        end
    end
    return true
end

local function restore(plan)
    local ok=true
    for id,row in pairs(plan.before) do
        if not set_record(id,row) then ok=false end
    end
    if not set_bootcmd(plan.bootcmd_before) then ok=false end
    if not verify(plan.before,plan.bootcmd_before) then ok=false end
    return ok
end

-- The marker is a durable recovery obligation, not a temporary staging
-- artifact. A failed write can be followed by a failed restore. Never clear
-- that marker unless all prior values (including bootcmd) read back equal.
local function abort_stage(job,before,bootcmd,reason)
    if not restore({before=before,bootcmd_before=bootcmd}) then
        return nil,"boot_config_stage_restore_unverified"
    end
    local disarmed,cleared=pcall(store.clear,job)
    if not disarmed or not cleared then
        return nil,"boot_config_stage_recovery_disarm_unverified"
    end
    return nil,reason
end

local function random_id()
    local raw=fs.readfile("/dev/urandom",16)
    return type(raw)=="string" and #raw==16 and nixio.bin.hexlify(raw) or nil
end

local function request_records(request)
    if type(request)~="table" or getmetatable(request)~=nil then
        return nil,"boot_config_request_invalid"
    end
    local out,ids={},{}
    for id,value in pairs(request) do
        if not FIELDS[id] or not valid(id,value) then
            return nil,"boot_config_request_invalid_"..tostring(id)
        end
        out[id]={present=true,value=value}
        ids[#ids+1]=id
    end
    table.sort(ids)
    if #ids<1 or #ids>4 then return nil,"boot_config_request_empty" end
    return out,ids
end

function M.stage(request)
    local candidate,ids=request_records(request)
    if not candidate then return nil,ids end
    local pending,why=store.read()
    if not pending then return nil,why end
    if pending.pending then return nil,"boot_config_transaction_already_pending" end
    local before,bootcmd=snapshot(ids)
    if not before then return nil,bootcmd end
    local job=random_id()
    if not job then return nil,"boot_config_job_id_unavailable" end
    local armed,arm_why=store.arm({
        job_id=job,before=before,candidate=candidate,bootcmd_before=bootcmd,
    })
    if not armed then return nil,arm_why end
    for _,id in ipairs(ids) do
        if not set_record(id,candidate[id]) then
            return abort_stage(job,before,bootcmd,
                "boot_config_candidate_write_failed")
        end
    end
    if not verify(candidate,nil) then
        return abort_stage(job,before,bootcmd,
            "boot_config_candidate_readback_failed")
    end
    -- Commit the trial-ready phase only after every candidate field is
    -- durable and independently verified. If interrupted earlier, the boot
    -- recovery hook sees "preparing" and restores, even if a partial
    -- candidate happens to match all desired values.
    local promoted,prepared=pcall(store.phase,job,"prepared",nil)
    if not promoted or not prepared then
        return abort_stage(job,before,bootcmd,
            "boot_config_prepare_phase_failed")
    end
    return {
        schema=1,status="BOOT_CONFIG_TRIAL_STAGED",job_id=job,
        fields=#ids,reboot_required=true,confirmation_required=true,
        timeout_seconds=180,contains_configuration_values=false,
    }
end

function M.status()
    local p,why=store.read()
    if not p then return nil,why end
    if not p.pending then return {schema=1,pending=false} end
    local fields={}
    for id in pairs(p.candidate) do fields[#fields+1]=id end
    table.sort(fields)
    return {
        schema=1,pending=true,job_id=p.job_id,phase=p.phase,
        fields=fields,confirmation_required=p.phase=="trial_running",
        recovery_required=p.phase=="preparing" or p.phase=="rollback_restored",
        reboot_required=p.phase=="prepared" or p.phase=="rollback_restored" or
                        p.phase=="preparing",
        contains_configuration_values=false,
    }
end

function M.boot_enter()
    local p,why=store.read()
    if not p then return nil,why end
    if not p.pending then return {status="NO_PENDING_BOOT_CONFIG_TRIAL",reboot_required=false} end
    local id=boot_id()
    if not id then return nil,"boot_id_unavailable" end
    if p.phase=="preparing" then
        -- A prior session died or returned before the write/readback and
        -- durable phase promotion finished. Never boot its candidate.
        if not restore(p) then
            return nil,"boot_config_interrupted_stage_restore_failed"
        end
        local ok,phase_why=store.phase(p.job_id,"rollback_restored",id)
        if not ok then return nil,phase_why end
        return {status="BOOT_CONFIG_INTERRUPTED_STAGE_RESTORED",
                reboot_required=true}
    elseif p.phase=="prepared" then
        if not verify(p.candidate,nil) then
            local restored=restore(p)
            if restored then store.phase(p.job_id,"rollback_restored",id) end
            return restored and
                {status="BOOT_CONFIG_PREBOOT_MISMATCH_RESTORED",reboot_required=true} or
                nil, restored and nil or "boot_config_preboot_restore_failed"
        end
        local ok,phase_why=store.phase(p.job_id,"trial_running",id)
        if not ok then return nil,phase_why end
        return {status="BOOT_CONFIG_TRIAL_RUNNING",reboot_required=false,job_id=p.job_id}
    elseif p.phase=="trial_running" then
        if p.boot_id==id then
            return {status="BOOT_CONFIG_TRIAL_RUNNING",reboot_required=false,job_id=p.job_id}
        end
        if not restore(p) then return nil,"boot_config_unconfirmed_restore_failed" end
        local ok,phase_why=store.phase(p.job_id,"rollback_restored",id)
        if not ok then return nil,phase_why end
        return {status="BOOT_CONFIG_UNCONFIRMED_REBOOT_RESTORED",reboot_required=true}
    elseif p.phase=="rollback_restored" then
        if not verify(p.before,p.bootcmd_before) then
            if not restore(p) then return nil,"boot_config_rollback_readback_failed" end
            return {status="BOOT_CONFIG_ROLLBACK_RESTORED",reboot_required=true}
        end
        local cleared,clear_why=store.clear(p.job_id)
        if not cleared then return nil,clear_why end
        return {status="BOOT_CONFIG_ROLLBACK_COMPLETE",reboot_required=false}
    end
    return nil,"boot_config_phase_invalid"
end

function M.confirm(job)
    local p,why=store.read()
    if not p then return nil,why end
    local id=boot_id()
    if not p.pending or p.job_id~=job or p.phase~="trial_running" or p.boot_id~=id then
        return nil,"boot_config_confirmation_state_mismatch"
    end
    if not verify(p.candidate,nil) then return nil,"boot_config_candidate_readback_failed" end
    local cleared,clear_why=store.clear(job)
    if not cleared then return nil,clear_why end
    return {
        schema=1,status="BOOT_CONFIG_TRIAL_CONFIRMED",
        confirmation_required=false,reboot_required=false,
        contains_configuration_values=false,
    }
end

function M.timeout()
    local p,why=store.read()
    if not p then return nil,why end
    if not p.pending or p.phase~="trial_running" then
        return {status="NO_RUNNING_BOOT_CONFIG_TRIAL",reboot_required=false}
    end
    local id=boot_id()
    if p.boot_id~=id then return nil,"boot_config_timeout_boot_changed" end
    if not restore(p) then return nil,"boot_config_timeout_restore_failed" end
    local ok,phase_why=store.phase(p.job_id,"rollback_restored",id)
    if not ok then return nil,phase_why end
    return {
        schema=1,status="BOOT_CONFIG_TRIAL_TIMEOUT_RESTORED",
        reboot_required=true,contains_configuration_values=false,
    }
end

M.WAIT_SECONDS=180
M.fields=FIELDS
return M
