local root=assert(arg[1],"overlay lua root required")
package.path=root.."/?.lua;"..package.path

local function ip(a,b,c,d) return table.concat({a,b,c,d},".") end
local function mac(a,b,c,d,e,f) return table.concat({a,b,c,d,e,f},":") end

package.preload["nixio"]=function()
    return {nanosleep=function() return true end}
end
package.preload["nixio.fs"]=function() return {} end
package.preload["8311.webutil"]=function() return {capture=function() return 0,"",false end} end
package.preload["8311.vlan_transition"]=function() return {} end
package.preload["8311.management_environment"]=function() return {} end
package.preload["8311.management_uci"]=function() return {} end
package.preload["8311.management_recovery_store"]=function() return {} end
package.preload["8311.management_runtime"]=function() return {} end
package.preload["8311.management_access"]=function() return {} end

local M=require "8311.management_transaction"

local request={
    vlan=100,ipaddr=ip('192','0','2','10'),netmask=ip('255','255','255','0'),
    gateway=ip('192','0','2','1'),dns_server=ip('192','0','2','53'),
    lct_mac=mac('02','00','00','00','00','10')
}

local function provider(opts)
    opts=opts or {}
    local calls={}
    local confirm_count=0
    local P={}
    local function hit(name)
        calls[#calls+1]=name
        return not (opts.fail==name)
    end
    function P.pending()
        hit("pending")
        if opts.pending then return {pending=true} end
        return {pending=false}
    end
    function P.snapshot()
        if not hit("snapshot") then return nil,"snapshot_failed" end
        return {uci={},raw={network="n",firewall="f"},environment="e"}
    end
    function P.plan()
        if not hit("plan") then return nil,"plan_failed" end
        return {changes_required=opts.no_change~=true}
    end
    function P.arm()
        if not hit("arm") then return nil,"arm_failed" end
        return {status="armed"}
    end
    function P.apply_environment()
        if not hit("apply_environment") then return nil,"env_failed" end
        return true
    end
    function P.apply_uci()
        if not hit("apply_uci") then return nil,"uci_failed" end
        return true
    end
    function P.apply_access()
        if not hit("apply_access") then return nil,"access_failed" end
        return true
    end
    function P.reload()
        if not hit("reload") then return nil,"reload_failed" end
        return true
    end
    function P.verify()
        hit("verify")
        if opts.verify_fail then return nil,"runtime_mismatch" end
        return {status="verified"}
    end
    function P.confirmed()
        hit("confirmed")
        confirm_count=confirm_count+1
        if opts.confirm_error then return nil,"confirm_state_failed" end
        return opts.confirm_after and confirm_count>=opts.confirm_after or false
    end
    function P.clear()
        if not hit("clear") then return nil,"clear_failed" end
        return true
    end
    function P.restore()
        if not hit("restore") or opts.restore_fail then return nil,"restore_failed" end
        return {status="restored"}
    end
    function P.sleep() hit("sleep") end
    return P,calls
end

local base="/var/tmp/aott-management-transaction-test-deadbeefdeadbeef"
local job=base.."/job"

local P,calls=provider({confirm_after=2})
local result=assert(M.fixture_transaction(base,job,request,P,3,2))
assert(result.status=="MANAGEMENT_TRANSACTION_CONFIRMED")
assert(result.runtime_verified==true)
assert(result.contains_configuration_values==false)
assert(table.concat(calls,","):find("arm,apply_environment,apply_uci,apply_access,reload,verify,confirmed,sleep,confirmed,clear",1,true))

P,calls=provider({})
result=assert(M.fixture_transaction(base,job,request,P,1,2))
assert(result.status=="MANAGEMENT_TRANSACTION_ROLLED_BACK")
assert(result.failure_reason=="management_confirmation_timeout")
assert(result.rollback_verified==true)
assert(calls[#calls]=="restore")

P,calls=provider({verify_fail=true})
result=assert(M.fixture_transaction(base,job,request,P,1,2))
assert(result.status=="MANAGEMENT_TRANSACTION_ROLLED_BACK")
assert(result.failure_reason=="runtime_mismatch")
assert(result.rollback_verified==true)
assert(table.concat(calls,","):find("verify,sleep,verify,restore",1,true))

P,calls=provider({fail="apply_environment"})
result=assert(M.fixture_transaction(base,job,request,P,1,1))
assert(result.status=="MANAGEMENT_TRANSACTION_ROLLED_BACK")
assert(result.failure_reason=="env_failed")
assert(calls[#calls]=="restore")

P,calls=provider({no_change=true})
result=assert(M.fixture_transaction(base,job,request,P,1,1))
assert(result.status=="MANAGEMENT_TRANSACTION_NO_CHANGE")
assert(result.runtime_verified==true)
local joined=table.concat(calls,",")
assert(not joined:find("arm",1,true))
assert(not joined:find("apply_environment",1,true))
assert(not joined:find("apply_uci",1,true))
assert(not joined:find("apply_access",1,true))

P,calls=provider({verify_fail=true,restore_fail=true})
local nope,why=M.fixture_transaction(base,job,request,P,1,1)
assert(nope==nil and why=="management_rollback_failed:restore_failed")

P,calls=provider({pending=true})
nope,why=M.fixture_transaction(base,job,request,P,1,1)
assert(nope==nil and why=="management_transaction_already_pending")

print("AOTT_V3_MANAGEMENT_TRANSACTION_PASS")
