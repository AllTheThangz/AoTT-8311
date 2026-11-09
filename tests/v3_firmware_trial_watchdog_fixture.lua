local root=assert(arg[1],"overlay lua root required")
package.path=root.."/?.lua;"..package.path

package.preload["nixio.fs"]=function() return {} end
package.preload["nixio"]=function() return {nanosleep=function() end} end
package.preload["luci.jsonc"]=function() return {parse=function() return nil end} end
package.preload["8311.webutil"]=function() return {capture=function() return 1,"",false end} end

local m=require "8311.firmware_trial_watchdog"
local BOOT="11111111-2222-3333-4444-555555555555"
local checks=0
local function same(a,b,label)
    checks=checks+1
    assert(a==b,"FW_TRIAL_FIXTURE:"..label.." expected="..tostring(b).." got="..tostring(a))
end
local function provider(statuses,status_cost)
    local P={statuses=statuses or {},i=0,confirmed=nil,states={},sleeps=0,rollbacks=0,clock=0,status_cost=status_cost or 0}
    function P.bank_status()
        P.i=P.i+1
        P.clock=P.clock+P.status_cost
        local s=P.statuses[math.min(P.i,#P.statuses)]
        return s
    end
    function P.boot_id() return BOOT end
    function P.prepare_root() return true end
    function P.write_state(r) P.states[#P.states+1]=r return true end
    function P.write_confirmed(r) P.confirmed=r return true end
    function P.read_confirmed()
        if P.confirmed then return P.confirmed end
        return nil,"absent"
    end
    function P.monotonic() return P.clock end
    function P.sleep(seconds)
        P.sleeps=P.sleeps+1
        P.clock=P.clock+(tonumber(seconds) or 0)
        return true
    end
    function P.rollback() P.rollbacks=P.rollbacks+1 return true end
    return P
end
local function status(active,committed)
    return {schema=1,active=active,committed=committed,pending=nil,
            running_trial=active~=committed,boot_contract=true}
end

local p=provider({status("B","B")})
local r=assert(m.run(p,4))
same(r.status,"NO_RUNNING_FIRMWARE_TRIAL","no_trial_status")
same(p.rollbacks,0,"no_trial_no_rollback")

p=provider({status("A","B")})
local c=assert(m.confirm(p))
same(c.confirmed,true,"confirm_running")
same(p.confirmed.active,"A","confirm_active")
same(p.confirmed.committed,"B","confirm_committed")

p=provider({status("A","B"),status("A","B")})
p.confirmed={boot_id=BOOT,active="A",committed="B"}
r=assert(m.run(p,4))
same(r.status,"FIRMWARE_TRIAL_WATCHDOG_CONFIRMED","already_confirmed")
same(p.rollbacks,0,"confirmed_no_rollback")

p=provider({status("A","B"),status("A","B"),status("A","B"),status("A","B")})
r=assert(m.run(p,4))
same(r.rollback_requested,true,"timeout_rollback_requested")
same(p.rollbacks,1,"timeout_one_rollback")
same(p.sleeps,2,"timeout_sleep_count")

p=provider({status("A","B"),status("B","B")})
r=assert(m.run(p,4))
same(r.status,"FIRMWARE_TRIAL_ENDED","state_ended")
same(p.rollbacks,0,"state_ended_no_rollback")

p=provider({status("A","B")})
local x,why=m.confirm(provider({status("B","B")}))
same(x,nil,"confirm_nontrial_nil")
same(why,"firmware_trial_not_running","confirm_nontrial_reason")

p=provider({status("A","B"),status("A","B"),status("A","B"),status("A","B"),status("A","B"),status("A","B")},1.5)
r=assert(m.run(p,10))
same(r.rollback_requested,true,"absolute_deadline_rollback")
same(p.rollbacks,1,"absolute_deadline_one_rollback")
checks=checks+1
assert(p.clock<=13.5,"FW_TRIAL_FIXTURE:absolute_deadline_exceeded clock="..tostring(p.clock))

-- This is a 180-second synthetic trial with Internet, HTTPS and SSH all
-- unavailable. No network callback is provided or needed; locally observed
-- boot state and monotonic time drive rollback to the committed bank.
p=provider({status("A","B")})
p.internet_reachable=false
p.ssh_reachable=false
p.https_reachable=false
r=assert(m.run(p))
same(r.rollback_requested,true,"offline_180sec_rollback")
same(p.rollbacks,1,"offline_exactly_one_reboot_request")
same(p.clock,180,"offline_monotonic_deadline")
same(p.sleeps,90,"offline_two_second_poll_count")

p=provider({status("A","B")})
p.internet_reachable=false
p.confirmed={boot_id=BOOT,active="A",committed="B"}
r=assert(m.run(p))
same(r.confirmed,true,"offline_local_confirmation")
same(p.rollbacks,0,"offline_confirmed_no_forced_reboot")

-- A corrupt/unreadable local bank-status contract is NOT considered a
-- verified rollback. Report this limitation rather than claiming safety.
p=provider({})
local missing_status, missing_reason=m.run(p)
same(missing_status,nil,"unreadable_status_not_proven")
same(missing_reason,nil,"unreadable_status_without_false_claim")
same(p.rollbacks,0,"unreadable_status_no_unverified_reboot")

same(m.WAIT_SECONDS,180,"default_timeout")
same(m.STEP_SECONDS,2,"step_seconds")
assert(checks>=15,"coverage")
print("AOTT_V3_FIRMWARE_TRIAL_WATCHDOG_PASS checks="..checks)
