local root=assert(arg[1],"overlay lua root required")
package.path=root.."/?.lua;"..package.path

package.preload["nixio"]=function()
    return {nanosleep=function()end}
end
package.preload["nixio.fs"]=function()
    return {}
end
package.preload["8311.pon_environment"]=function()return{}end
package.preload["8311.pon_config_recovery"]=function()return{}end
package.preload["8311.pon_config_uci"]=function()return{}end
package.preload["8311.pon_mib_runtime"]=function()return{}end
package.preload["8311.pon_config_runtime"]=function()return{}end
package.preload["8311.webutil"]=function()return{}end

local tx=require "8311.pon_config_transaction"
local testroot="/var/tmp/aott-pon-transaction-test-0123456789abcdef"
local jobdir=testroot.."/job"
local secret="TEST-PLOAM-SECRET-NEVER-RETURN"
local checks=0
local function same(a,b,label)
    checks=checks+1
    assert(a==b,"PON_TX:"..label.." expected="..tostring(b).." got="..tostring(a))
end
local function no_secret(value)
    if type(value)=="string" then
        assert(not value:find(secret,1,true),"PON_TX:secret_leak")
    elseif type(value)=="table" then
        for k,v in pairs(value) do no_secret(k);no_secret(v) end
    end
end

local function provider(opts)
    opts=opts or {}
    local log={}
    local confirm_count=0
    local P={}
    function P.pending() log[#log+1]="pending";return {pending=false} end
    function P.snapshot()
        log[#log+1]="snapshot"
        return {baseline=true}
    end
    function P.plan(_,changes)
        log[#log+1]="plan"
        return {changes_required=opts.nochange~=true,changes=changes,records={}}
    end
    function P.arm() log[#log+1]="arm";return {status="armed"} end
    function P.apply_environment()
        log[#log+1]="environment"
        if opts.fail=="environment" then return nil,"synthetic_env_failure" end
        return true
    end
    function P.apply_uci()
        log[#log+1]="uci"
        if opts.fail=="uci" then return nil,"synthetic_uci_failure" end
        return true
    end
    function P.apply_mib()
        log[#log+1]="mib"
        if opts.fail=="mib" then return nil,"synthetic_mib_failure" end
        return true
    end
    function P.apply_aux()
        log[#log+1]="aux"
        if opts.fail=="aux" then return nil,"synthetic_aux_failure" end
        return true
    end
    function P.restart()
        log[#log+1]="restart"
        if opts.fail=="restart" then return nil,"synthetic_restart_failure" end
        return true
    end
    function P.verify()
        log[#log+1]="verify"
        if opts.fail=="verify" then return nil,"synthetic_verify_failure" end
        return {status="verified"}
    end
    function P.phase(_,phase)
        log[#log+1]="phase:"..phase
        if opts.fail=="phase" then return nil,"synthetic_phase_failure" end
        return true
    end
    function P.confirmed()
        log[#log+1]="confirmed"
        confirm_count=confirm_count+1
        if opts.confirm_error then return nil,"synthetic_confirm_failure" end
        return opts.confirm_after and confirm_count>=opts.confirm_after or false
    end
    function P.clear()
        log[#log+1]="clear"
        if opts.fail=="clear" then return nil,"synthetic_clear_failure" end
        return true
    end
    function P.restore(_,reload)
        log[#log+1]="restore:"..tostring(reload)
        if opts.fail=="restore" then return nil,"synthetic_restore_failure" end
        return {pon_registered_o5_1=true}
    end
    function P.sleep() log[#log+1]="sleep" end
    return P,log
end

local changes={reg_id_hex=secret,gpon_sn="TEST00000001"}

local p,log=provider({confirm_after=2})
local result=assert(tx.fixture_transaction(testroot,jobdir,changes,p,3,2))
same(result.status,"PON_TRANSACTION_CONFIRMED","confirmed_status")
same(result.pon_registered_o5_1,true,"confirmed_o5")
same(result.olt_per_field_effect_proven,false,"no_false_olt_proof")
same(result.contains_configuration_values,false,"redacted")
same(table.concat(log,","):match("snapshot,plan,arm,environment,uci,mib,aux,restart")~=nil,true,"arm_before_mutation")
same(log[#log],"clear","confirmed_clear")
no_secret(result)

p,log=provider({fail="mib"})
result=assert(tx.fixture_transaction(testroot,jobdir,changes,p,1,1))
same(result.status,"PON_TRANSACTION_ROLLED_BACK","mib_rollback")
same(result.rollback_verified,true,"mib_rollback_verified")
same(log[#log],"restore:true","mib_restore")
no_secret(result)

p,log=provider({fail="verify"})
result=assert(tx.fixture_transaction(testroot,jobdir,changes,p,1,2))
same(result.status,"PON_TRANSACTION_ROLLED_BACK","verify_rollback")
same(log[#log],"restore:true","verify_restore")
no_secret(result)

p,log=provider({})
result=assert(tx.fixture_transaction(testroot,jobdir,changes,p,2,1))
same(result.status,"PON_TRANSACTION_ROLLED_BACK","timeout_rollback")
same(result.failure_reason,"pon_confirmation_timeout","timeout_reason")
same(log[#log],"restore:true","timeout_restore")
no_secret(result)

p,log=provider({nochange=true})
result=assert(tx.fixture_transaction(testroot,jobdir,changes,p,1,1))
same(result.status,"PON_TRANSACTION_NO_CHANGE","noop_status")
same(table.concat(log,","):find("arm",1,true),nil,"noop_no_arm")
same(result.olt_per_field_effect_proven,false,"noop_no_false_olt")
no_secret(result)

p,log=provider({confirm_error=true})
result=assert(tx.fixture_transaction(testroot,jobdir,changes,p,1,1))
same(result.status,"PON_TRANSACTION_ROLLED_BACK","confirm_error_rollback")
same(log[#log],"restore:true","confirm_error_restore")

same(checks>=18,true,"coverage")
print("AOTT_V3_PON_TRANSACTION_PASS checks="..checks)
