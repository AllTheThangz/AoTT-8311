-- P0-09 synthetic power-loss/failed-write boot configuration regression.
-- Memory-only native firmware environment and recovery store. No device I/O.
local root=assert(arg[1],"Lua overlay root required")
package.path=root.."/?.lua;"..package.path

local env,plan,mode,sequence
local function reset()
    env={bootdelay="3",uart_select="on",
         ["8311_failsafe_delay"]="15",["8311_persist_root"]="1",
         bootcmd="run_existing_boot"}
    plan=nil
    mode={}
    sequence=0
end
reset()

package.preload["8311.tools"]=function()
    local M={}
    function M.fwenv_read_all()
        local out={}
        for k,v in pairs(env) do out[k]=v end
        if mode.bad_readback then
            mode.bad_readback=false
            out.bootdelay="mismatched_readback"
        end
        return out
    end
    local function write(key,val)
        if mode.fail_restore and key=="bootdelay" and val=="3" then
            return false
        end
        if val==nil or val=="" then env[key]=nil else env[key]=val end
        if mode.fail_candidate and key=="bootdelay" and val=="1" then
            mode.fail_candidate=false
            if mode.throw_after_write then
                mode.throw_after_write=false
                error("synthetic postwrite exception")
            end
            return false
        end
        return true
    end
    function M.fw_setenv(args) return write(args[1],args[2]) end
    function M.fw_setenv_8311(args)
        return write("8311_"..args[1],args[2])
    end
    return M
end
package.preload["nixio.fs"]=function()
    return {
        readfile=function(path)
            if path=="/proc/sys/kernel/random/boot_id" then
                return "11111111-2222-3333-4444-555555555555\n"
            end
            if path=="/dev/urandom" then
                sequence=sequence+1
                return string.rep(string.char(sequence),16)
            end
        end
    }
end
package.preload["nixio"]=function()
    return {bin={hexlify=function(raw)
        return (raw:gsub(".",function(x)
            return string.format("%02x",string.byte(x))
        end))
    end}}
end
package.preload["8311.boot_config_store"]=function()
    local M={}
    function M.read()
        if not plan then return {pending=false} end
        local out={}
        for k,v in pairs(plan) do out[k]=v end
        out.pending=true
        return out
    end
    function M.arm(record)
        if plan then return nil,"already_pending" end
        plan=record
        plan.schema=1
        plan.phase="preparing"
        plan.boot_id=nil
        return {status="ARMED"}
    end
    function M.phase(id,phase,boot_id)
        if not plan or plan.job_id~=id then
            return nil,"wrong_job"
        end
        if phase=="prepared" and mode.fail_promotion then
            mode.fail_promotion=false
            return nil,"injected_atomic_promotion_failure"
        end
        plan.phase=phase
        plan.boot_id=boot_id
        return true
    end
    function M.clear(id)
        if not plan or plan.job_id~=id then return nil,"wrong_job" end
        if mode.fail_clear then
            mode.fail_clear=false
            return nil,"injected_disarm_error"
        end
        plan=nil
        return {status="CLEARED"}
    end
    return M
end
local tx=require "8311.boot_config_transaction"
local store=require "8311.boot_config_store"
local checks=0
local function same(actual,expected,name)
    checks=checks+1
    assert(actual==expected,"BOOT_CRASH:"..name..
        " expected="..tostring(expected).." actual="..tostring(actual))
end

-- Baseline: a successful candidate is durably promoted to "prepared".
reset()
local first=assert(tx.stage({bootdelay="1"}))
same(first.status,"BOOT_CONFIG_TRIAL_STAGED","success")
same(plan.phase,"prepared","staged_then_promoted")
same(env.bootdelay,"1","candidate_persisted")
same(tx.status().recovery_required,false,"prepared_is_not_interrupted")
same(tx.status().confirmation_required,false,"not_yet_running")

-- Simulated SIGKILL/power loss after all writes but before promotion. A
-- value-equivalent candidate remains UNQUALIFIED when phase is preparing.
reset()
assert(store.arm({
    job_id=string.rep("a",32),
    before={bootdelay={present=true,value="3"}},
    candidate={bootdelay={present=true,value="1"}},
    bootcmd_before={present=true,value="run_existing_boot"},
}))
env.bootdelay="1"
same(tx.status().phase,"preparing","preparing_status")
same(tx.status().recovery_required,true,"interrupted_recovery_flag")
same(tx.status().confirmation_required,false,"not_trial_while_preparing")
local interrupted=assert(tx.boot_enter())
same(interrupted.status,"BOOT_CONFIG_INTERRUPTED_STAGE_RESTORED",
     "preparing_not_promoted_to_trial")
same(interrupted.reboot_required,true,"interrupted_recovery_boot_required")
same(env.bootdelay,"3","interrupted_restored")
same(plan.phase,"rollback_restored","interrupted_restoration_recorded")
same(tx.boot_enter().status,"BOOT_CONFIG_ROLLBACK_COMPLETE",
     "interrupted_cleanup")
same(tx.status().pending,false,"interrupted_marker_cleared")

-- Partial persistent write followed by a clean rollback disarms only after
-- verifying the previous boot environment, including bootcmd.
reset()
mode.fail_candidate=true
local got,why=tx.stage({bootdelay="1"})
same(got,nil,"failed_stage_rejected")
same(why,"boot_config_candidate_write_failed","failed_stage_code")
same(env.bootdelay,"3","failed_stage_restored")
same(env.bootcmd,"run_existing_boot","failed_stage_restored_bootcmd")
same(tx.status().pending,false,"verified_stage_rollback_disarmed")

-- The setter can write a candidate and throw before returning its result.
reset()
mode.fail_candidate=true
mode.throw_after_write=true
got,why=tx.stage({bootdelay="1"})
same(got,nil,"postwrite_exception_rejected")
same(why,"boot_config_candidate_write_failed","postwrite_exception_redacted")
same(env.bootdelay,"3","postwrite_exception_restored")
same(tx.status().pending,false,"postwrite_exception_disarmed")

-- If restoration fails, retain a durable non-trial recovery obligation.
reset()
mode.fail_candidate=true
mode.fail_restore=true
got,why=tx.stage({bootdelay="1"})
same(got,nil,"failed_restore_rejected")
same(why,"boot_config_stage_restore_unverified","failed_restore_code")
same(env.bootdelay,"1","failed_restore_partial_candidate")
same(plan.phase,"preparing","failed_restore_marker_preserved")
mode.fail_restore=false
same(tx.boot_enter().status,"BOOT_CONFIG_INTERRUPTED_STAGE_RESTORED",
     "boot_retry_restoration")
same(env.bootdelay,"3","boot_retry_prior_value")
same(tx.boot_enter().status,"BOOT_CONFIG_ROLLBACK_COMPLETE",
     "boot_retry_cleanup")

-- A verified rollback whose disarm fails must remain pending and visible.
reset()
mode.fail_candidate=true
mode.fail_clear=true
got,why=tx.stage({bootdelay="1"})
same(got,nil,"failed_disarm_rejected")
same(why,"boot_config_stage_recovery_disarm_unverified","failed_disarm_code")
same(env.bootdelay,"3","failed_disarm_restored")
same(plan.phase,"preparing","failed_disarm_keeps_marker")
same(tx.boot_enter().status,"BOOT_CONFIG_INTERRUPTED_STAGE_RESTORED",
     "failed_disarm_boot_recovery")
same(tx.boot_enter().status,"BOOT_CONFIG_ROLLBACK_COMPLETE",
     "failed_disarm_cleanup")

-- A failed phase promotion cannot return a staged success receipt.
reset()
mode.fail_promotion=true
got,why=tx.stage({bootdelay="1"})
same(got,nil,"failed_promotion_rejected")
same(why,"boot_config_prepare_phase_failed","failed_promotion_code")
same(env.bootdelay,"3","failed_promotion_restored")
same(tx.status().pending,false,"failed_promotion_disarmed")

same(checks>=36,true,"fault_coverage")
print("AOTT_V3_BOOT_CONFIG_CRASH_RECOVERY_PASS checks="..checks)
