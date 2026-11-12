-- V3r4 H-018 history settings transaction, memory-only UCI/service fakes.
-- Never opens a socket, changes a service or touches real filesystem.
local root=assert(arg[1],"overlay Lua root")
package.path=root.."/?.lua;"..package.path

local function copy(tbl)
    local o={}
    for k,v in pairs(tbl) do o[k]=v end
    return o
end
local orig={
    enabled="0",pon_interval_seconds="60",host_interval_seconds="60",
    ram_sample_limit="120",ram_event_limit="128",
}
local store=copy(orig)
local running=false
local fail_commit=false
local fail_restore=false
local corrupt_after_commit=false
local omit_after_commit=false
local service_claim_only=false
local service_fail=false
local postcommit_exception=false
local writes=0
local services=0
local locks=0
local assertions=0
local function same(a,b,message)
    assertions=assertions+1
    assert(a==b,"HISTORY_TRANSACTION:"..message.." got="..
           tostring(a).." expected="..tostring(b))
end
local function reset()
    store=copy(orig)
    running=false
    fail_commit=false;fail_restore=false
    corrupt_after_commit=false;service_fail=false
    omit_after_commit=false;service_claim_only=false
    postcommit_exception=false
    writes=0;services=0;locks=0
end
package.preload["luci.model.uci"]=function()
    return {cursor=function()
        local staged=copy(store)
        return {
            get_all=function(_,pkg,section)
                assert(pkg=="aott_history" and section=="main")
                return copy(staged)
            end,
            set=function(_,pkg,section,key,value)
                assert(pkg=="aott_history" and section=="main")
                if value=="history" and key=="history" then return true end
                staged[key]=value
                return true
            end,
            commit=function()
                writes=writes+1
                if fail_restore and writes>=2 then return false end
                if fail_commit then
                    fail_commit=false
                    store=copy(staged)
                    return false
                end
                store=copy(staged)
                if corrupt_after_commit then
                    corrupt_after_commit=false
                    store.host_interval_seconds="300"
                end
                if omit_after_commit then
                    omit_after_commit=false
                    store.host_interval_seconds=nil
                end
                if postcommit_exception then
                    postcommit_exception=false
                    error("synthetic untrusted after-write exception")
                end
                return true
            end,
        }
    end}
end
package.preload["8311.webutil"]=function()
    return {
        digest_text=function(_) return string.rep("a",64) end,
        lock=function(path)
            same(path,"/tmp/8311-history-config.lock","fixed_lock")
            locks=locks+1
            return {close=function()
                locks=locks-1
            end}
        end,
        capture=function(argv,limit)
            services=services+1
            same(limit,1024,"bounded_service_output")
            same(argv[1],"/etc/init.d/8311-history","fixed_history_service")
            local op=argv[2]
            if service_fail then
                service_fail=false
                return 1,"synthetic failure",false
            end
            if op=="restart" and not service_claim_only then running=true end
            if op=="stop" then running=false end
            return 0,"",false
        end,
    }
end
package.preload["nixio.fs"]=function()
    return {stat=function() return {type="directory"} end}
end
package.preload["8311.history_process_lock"]=function()
    return {
        PRODUCTION_DIR="/var/run/aott-history",
        writer_present=function()
            return running,running and "writer_present" or "not_started"
        end
    }
end
local config=require "8311.history_config"
local function form(changes)
    local snap=assert(config.snapshot())
    local out={revision=snap.revision}
    for key in pairs(orig) do out[key]=snap[key] end
    for key,val in pairs(changes) do out[key]=val end
    return out
end
local function saved_is_original()
    for k,v in pairs(orig) do same(store[k],v,"old_settings:"..k) end
end

reset()
local unchanged=assert(config.apply(form({})))
same(unchanged.enabled,"0","no_op_keeps_disabled")
same(writes,0,"no_op_no_flash_write")
same(services,0,"no_op_no_service_restart")
same(locks,0,"no_op_releases_lock")

reset()
local result=assert(config.apply(form({
    enabled="1",host_interval_seconds="30",
    ram_sample_limit="300",
})))
same(result.enabled,"1","configured_enabled")
same(result.service_running,true,"verified_worker_running")
same(store.host_interval_seconds,"30","persisted_host_interval")
same(store.ram_sample_limit,"300","persisted_ram_cap")
same(writes,1,"one_committed_transaction")
same(locks,0,"success_unlocks")

reset()
fail_commit=true
result,why=config.apply(form({host_interval_seconds="30"}))
same(result,nil,"partial_write_rejected")
same(why,"History write failed; previous settings restored and verified",
     "partial_write_truthful")
saved_is_original()
same(writes,2,"write_and_restore_committed")
same(locks,0,"write_failure_unlocks")

reset()
postcommit_exception=true
result,why=config.apply(form({host_interval_seconds="30"}))
same(result,nil,"postcommit_exception_rejected")
same(why,"History write failed; previous settings restored and verified",
     "postcommit_exception_restored")
saved_is_original()

reset()
corrupt_after_commit=true
result,why=config.apply(form({host_interval_seconds="30"}))
same(result,nil,"readback_mismatch_rejected")
same(why,"History activation/readback failed; previous settings restored and verified",
     "readback_restored_not_false_success")
saved_is_original()

reset()
omit_after_commit=true
result,why=config.apply(form({enabled="1"}))
same(result,nil,"missing_explicit_uci_rejected")
same(why,"History activation/readback failed; previous settings restored and verified",
     "explicit_uci_absence_not_default_success")
saved_is_original()

reset()
service_claim_only=true
result,why=config.apply(form({enabled="1"}))
same(result,nil,"lying_service_success_rejected")
same(why,"History activation/readback failed; previous settings restored and verified",
     "service_started_claim_not_runtime_proof")
saved_is_original()
same(running,false,"lying_worker_not_running")

reset()
service_fail=true
result,why=config.apply(form({enabled="1"}))
same(result,nil,"service_failure_rejected")
same(why,"History activation/readback failed; previous settings restored and verified",
     "service_fail_restored")
saved_is_original()
same(running,false,"service_after_rollback_stopped")

reset()
fail_commit=true
fail_restore=true
result,why=config.apply(form({host_interval_seconds="30"}))
same(result,nil,"failed_rollback_rejected")
same(why,"History write failed; rollback unverified, inspect saved and running settings",
     "rollback_unverified_not_claimed")
same(store.host_interval_seconds,"30","partial_settings_remain_visible")
same(locks,0,"failed_rollback_unlocks")

reset()
result,why=config.apply(form({host_interval_seconds="1"}))
same(result,nil,"invalid_interval_rejected")
same(writes,0,"invalid_no_flash_write")
same(services,0,"invalid_no_restart")
same(locks,0,"invalid_no_lock")

same(assertions>=52,true,"assertion_floor")
print("AOTT_V3R4_HISTORY_SETTINGS_TRANSACTION_PASS checks="..assertions)
