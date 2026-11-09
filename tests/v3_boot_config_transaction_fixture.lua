local root=assert(arg[1],"overlay lua root required")
package.path=root.."/?.lua;"..package.path

local env={
    bootdelay="3",uart_select="on",["8311_failsafe_delay"]="15",
    ["8311_persist_root"]="1",bootcmd="custom bootcmd",
}
local boot="11111111-1111-1111-1111-111111111111"
local plan=nil
local seq=0

package.preload["8311.tools"]=function()
    local M={}
    function M.fwenv_read_all()
        local out={};for k,v in pairs(env) do out[k]=v end;return out
    end
    local function set(key,value)
        if value==nil or value=="" then env[key]=nil else env[key]=value end
        return true
    end
    function M.fw_setenv(t) return set(t[1],t[2]) end
    function M.fw_setenv_8311(t) return set("8311_"..t[1],t[2]) end
    return M
end

package.preload["nixio.fs"]=function()
    return {
        readfile=function(path,len)
            if path=="/proc/sys/kernel/random/boot_id" then return boot.."\n" end
            if path=="/dev/urandom" then
                seq=seq+1
                return string.rep(string.char(seq),16)
            end
        end
    }
end

package.preload["nixio"]=function()
    return {bin={hexlify=function(raw)
        return (raw:gsub(".",function(c)return string.format("%02x",string.byte(c))end))
    end}}
end

package.preload["8311.boot_config_store"]=function()
    local M={}
    M.fields={bootdelay=true,uart_select=true,failsafe_delay=true,persist_root=true}
    function M.read()
        if not plan then return {pending=false} end
        local p={};for k,v in pairs(plan) do p[k]=v end;p.pending=true;return p
    end
    function M.arm(p)
        assert(not plan)
        plan=p;plan.schema=1;plan.phase="prepared";plan.boot_id=nil
        return {status="BOOT_CONFIG_RECOVERY_ARMED",job_id=p.job_id}
    end
    function M.phase(job,phase,id)
        assert(plan and plan.job_id==job)
        plan.phase=phase;plan.boot_id=id
        return true
    end
    function M.clear(job)
        assert(plan and plan.job_id==job)
        plan=nil
        return {status="BOOT_CONFIG_RECOVERY_CLEARED"}
    end
    return M
end

local tx=require "8311.boot_config_transaction"
local checks=0
local function same(a,b,label)
    checks=checks+1
    assert(a==b,"BOOT_TX:"..label.." expected="..tostring(b).." got="..tostring(a))
end

local staged=assert(tx.stage({
    bootdelay="1",uart_select="off",failsafe_delay="30",persist_root="0",
}))
same(staged.status,"BOOT_CONFIG_TRIAL_STAGED","stage")
same(staged.reboot_required,true,"stage_reboot")
same(env.bootdelay,"1","candidate_bootdelay")
same(env.uart_select,"off","candidate_uart")
same(env["8311_failsafe_delay"],"30","candidate_delay")
same(env["8311_persist_root"],"0","candidate_persist")
same(env.bootcmd,"custom bootcmd","bootcmd_not_changed_by_stage")

local entered=assert(tx.boot_enter())
same(entered.status,"BOOT_CONFIG_TRIAL_RUNNING","first_boot")
local status=assert(tx.status())
same(status.phase,"trial_running","trial_phase")
same(status.confirmation_required,true,"confirm_required")

local confirmed=assert(tx.confirm(staged.job_id))
same(confirmed.status,"BOOT_CONFIG_TRIAL_CONFIRMED","confirm")
same(tx.status().pending,false,"cleared_after_confirm")

-- Timeout restores all candidate fields and bootcmd.
local staged2=assert(tx.stage({
    bootdelay="2",uart_select="on",failsafe_delay="45",persist_root="0",
}))
assert(tx.boot_enter())
env.bootcmd="run ubi_init; ubi remove rootfs_data; run flash_flash"
local timed=assert(tx.timeout())
same(timed.reboot_required,true,"timeout_reboot")
same(env.bootdelay,"1","timeout_restore_bootdelay")
same(env.uart_select,"off","timeout_restore_uart")
same(env["8311_failsafe_delay"],"30","timeout_restore_delay")
same(env["8311_persist_root"],"0","timeout_restore_persist_previous")
same(env.bootcmd,"custom bootcmd","timeout_restore_bootcmd")

-- A new boot after timeout completes cleanup.
boot="22222222-2222-2222-2222-222222222222"
local cleanup=assert(tx.boot_enter())
same(cleanup.status,"BOOT_CONFIG_ROLLBACK_COMPLETE","rollback_cleanup")
same(tx.status().pending,false,"rollback_plan_cleared")

-- A reboot during an unconfirmed trial restores prior state and requests one
-- recovery reboot.
local staged3=assert(tx.stage({bootdelay="0"}))
assert(tx.boot_enter())
boot="33333333-3333-3333-3333-333333333333"
local recovered=assert(tx.boot_enter())
same(recovered.status,"BOOT_CONFIG_UNCONFIRMED_REBOOT_RESTORED","unconfirmed_reboot")
same(recovered.reboot_required,true,"unconfirmed_reboot_required")
same(env.bootdelay,"1","unconfirmed_restore_value")

-- Invalid/mixed keys fail before mutation.
local before=env.bootdelay
local bad=tx.stage({gpon_sn="ABCD12345678"})
same(bad,nil,"unknown_refused")
same(env.bootdelay,before,"unknown_no_write")

same(checks>=25,true,"coverage")
print("AOTT_V3_BOOT_CONFIG_TRANSACTION_PASS checks="..checks)
