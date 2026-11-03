-- H-023 offline lifecycle and kernel-lock ownership integration fixture.
-- Source-only injected reader. Never accesses a live PON or service.
local root=assert(arg[1],"Offline MIPS rootfs is required")
local lib=assert(arg[2],"History library root is required")
local overlay=assert(arg[3],"Vendor source overlay root is required")
local mode=assert(arg[4],"Fixture mode is required")
local directory=assert(arg[5],"Private test directory is required")
package.path=lib.."/?.lua;"..overlay.."/?.lua;"..
    root.."/usr/lib/lua/?.lua;"..root.."/usr/lib/lua/?/init.lua;"..
    package.path
package.cpath=root.."/usr/lib/lua/?.so;"..package.cpath

local prefs=require "8311.history_preferences"
local lifecycle=require "8311.history_lifecycle"
local guarded=require "8311.history_guarded_collector"
local checks=0
local function ok(value,name)
    checks=checks+1
    assert(value,"H023_LIFECYCLE_FIXTURE_FAILED:"..name)
end
local function eq(a,b,name) ok(a==b,name) end
local capabilities={kind="source_only",native_qualified=true}
local defaults=prefs.defaults()
local settings=assert(prefs.simulate(defaults,{
    sampling_enabled=true,pon_interval_seconds=60,
    host_interval_seconds=120,
},1,capabilities))

local BOOT="11111111-2222-4333-8444-555555555555"
local BOOT_RESTART="22222222-3333-4444-8555-666666666666"
local function fake()
    local obj={uptime=100,commands=0,reads=0,boot=BOOT,boot_invalid=false,
               pon_fail=false,pon=51}
    function obj.read(path,max)
        obj.reads=obj.reads+1
        if path=="/proc/sys/kernel/random/boot_id" then
            return obj.boot_invalid and "invalid-boot-id\n" or obj.boot.."\n"
        elseif path=="/proc/uptime" then
            return string.format("%.2f 15.00\n",obj.uptime)
        elseif path=="/sys/class/net/eth0_0/speed" then
            return "10000\n"
        end
        error("H023_UNEXPECTED_KERNEL_READ")
    end
    function obj.run(argv,max)
        obj.commands=obj.commands+1
        local s=table.concat(argv," ")
        if s=="/usr/bin/timeout -k 1 3 /usr/bin/pon psg" then
            if obj.pon_fail then return 1,"",false end
            return 0,"current="..obj.pon.."\n",false
        elseif s=="/usr/bin/timeout -k 1 4 /usr/sbin/ethtool -S eth0_0" then
            local r=math.floor(obj.uptime*1250000)
            return 0,"RxGoodBytes: "..tostring(r)..
                "\nTxGoodBytes: "..tostring(r*2).."\n",false
        end
        error("H023_UNEXPECTED_NATIVE_ARGV")
    end
    return obj
end
local bad,badreason=lifecycle.new(directory,settings,capabilities,"enable_live")
eq(bad,nil,"live_mode_never_accepted")
eq(badreason,"hardware_lifecycle_not_qualified","explicit_hardware_gate")
bad,badreason=lifecycle.new(directory,defaults,capabilities,"offline_synthetic")
eq(bad,nil,"disabled_default_rejected")
eq(badreason,"unavailable_lifecycle_feature","disabled_setting_not_started")
bad,badreason=lifecycle.new(directory,settings,
    {kind="source_only",native_qualified=false},"offline_synthetic")
eq(bad,nil,"unqualified_capabilities_rejected")
eq(badreason,"invalid_source_lifecycle","unqualified_reason")

local runner,initial=assert(lifecycle.new(directory,settings,capabilities,
    "offline_synthetic"))
eq(initial.status,"stopped","manual_start_required")
eq(initial.running,false,"initial_not_running")
eq(initial.lifetime_starts,0,"no_implicit_start")
eq(initial.no_background_service,true,"no_hidden_service")
eq(initial.no_device_write,true,"no_device_write")
eq(initial.no_flash_write,true,"no_flash_write")
eq(initial.no_alert_or_network_delivery,true,"no_external_delivery")
eq(initial.source_only_not_deployed,true,"source_only")
local provider=fake()
local no_auto=assert(lifecycle.step(runner,100,provider))
eq(no_auto.status,"stopped_no_auto_start","step_does_not_start")
eq(provider.commands,0,"no_native_commands_when_stopped")

-- A mutated caller draft must not change the already admitted plan.
settings.values.pon_interval_seconds=30
settings.values.host_interval_seconds=30
local first=assert(lifecycle.start(runner,100))
eq(first.status,"running","explicit_start")
eq(first.owns_kernel_lock,true,"kernel_ownership_required")
eq(first.lifetime_starts,1,"first_start_counted")
settings.values.pon_interval_seconds=60
settings.values.host_interval_seconds=120
eq(assert(lifecycle.start(runner,100)).status,
   "already_running","duplicate_start_no_second_collector")
local baseline=assert(lifecycle.step(runner,100,provider))
eq(baseline.status,"sample_accepted","initial_sample")
eq(baseline.has_rate,false,"baseline_no_rate")
eq(provider.commands,2,"initial_bounded_two_probes")
provider.uptime=101
eq(assert(lifecycle.step(runner,101,provider)).status,
   "not_due","no_polling_before_deadline")
eq(provider.commands,2,"not_due_does_not_spawn")
provider.uptime=160
local pon=assert(lifecycle.step(runner,160,provider))
eq(pon.due_pon,true,"pon_due_60")
eq(pon.due_host,false,"host_not_due_60")
eq(pon.host_observation,"not_sampled","skipped_not_failed")
eq(provider.commands,3,"only_one_native_probe_at_160")
provider.uptime=220
local rates=assert(lifecycle.step(runner,220,provider))
eq(rates.due_pon,true,"both_pon_due_at_220")
eq(rates.due_host,true,"both_host_due_at_220")
eq(rates.has_rate,true,"real_counter_rate")
eq(provider.commands,5,"fixed_reader_never_duplicates")
local history=assert(lifecycle.history(runner,"hour"))
eq(#history.samples,3,"three_retained_observations")
eq(history.windows.hour.rx.covered_seconds,120,
   "only_real_eth_counter_interval_counted")
eq(history.actual_isp_uptime_unverified,true,"not_internet_uptime")
local json=assert(lifecycle.export_json(runner,"hour"))
ok(json:find('"not_sampled"',1,true)~=nil,"not_sampled_exported")
ok(json:find(BOOT,1,true)==nil,"boot_identity_not_exported")

-- Source-only lock contention should not generate a storm of restart
-- attempts. The second lifecycle gets a bounded retry window.
local contender=assert(lifecycle.new(directory,settings,capabilities,
                                     "offline_synthetic"))
local busy=assert(lifecycle.start(contender,225))
eq(busy.status,"owner_busy","kernel_owner_prevents_second_start")
eq(busy.next_start_uptime,285,"contention_recheck_delayed")
eq(busy.failed_start_count,1,"contention_counts_once")
local still=assert(lifecycle.step(contender,240,provider))
eq(still.status,"cooldown_not_elapsed","no_hidden_timer")
local early=assert(lifecycle.start(contender,284))
eq(early.status,"cooldown_not_elapsed","no_early_restart")
eq(early.failed_start_count,1,"no_spin_on_early_start")
eq(provider.commands,5,"no_extra_native_commands_from_contender")

-- Four consecutive failed native read cycles trigger an orderly,
-- lock-releasing cooldown rather than an unbounded restart loop.
provider.boot_invalid=true
for index,now in ipairs({280,295,325,385}) do
    provider.uptime=now
    local result=assert(lifecycle.step(runner,now,provider))
    if index<4 then
        eq(result.status,"reader_backoff",
           "reader_error_backoff_"..index)
        eq(result.consecutive_reader_failures,index,
           "consecutive_errors_"..index)
    else
        eq(result.status,"cooldown","fourth_error_cooldown")
        eq(result.owns_kernel_lock,false,
           "cooldown_released_kernel_lock")
        eq(result.next_start_uptime,445,"restart_delayed_60")
        eq(result.restart_count,1,"first_controlled_restart")
    end
end
eq(provider.commands,5,"bad_boot_does_not_start_native_process")
local inaccessible,why=lifecycle.history(runner,"hour")
eq(inaccessible,nil,"no_fake_history_after_collector_closed")
eq(why,"collector_not_running","no_history_when_not_running")
local waiting=assert(lifecycle.step(runner,400,provider))
eq(waiting.status,"cooldown_not_elapsed","not_auto_restarting")
eq(assert(lifecycle.start(runner,444)).status,
   "cooldown_not_elapsed","restart_not_early")

-- Once the prior collector releases the stable file inode, the second
-- process/session can acquire it, but only after its own cool-off.
local handoff=assert(lifecycle.start(contender,400))
eq(handoff.status,"running","other_session_acquires_after_release")
eq(handoff.failed_start_count,0,"successful_start_resets_contention")
eq(handoff.lifetime_starts,1,"second_session_started")
eq(assert(lifecycle.stop(contender)).status,"stopped","manual_stop")
eq(assert(lifecycle.step(contender,401,provider)).status,
   "stopped_no_auto_start","manual_stop_is_not_auto_restart")
eq(assert(lifecycle.shutdown(contender)).phase,
   "closed","explicit_shutdown_closes")

provider.boot_invalid=false
local resumed=assert(lifecycle.start(runner,445))
eq(resumed.status,"running","explicit_restart_after_cooldown")
eq(resumed.lifetime_starts,2,"lifetime_started_twice")
eq(resumed.restart_count,1,"one_crash_cycle")
provider.uptime=445
eq(assert(lifecycle.step(runner,445,provider)).status,
   "sample_accepted","recovered_collector_can_sample")
provider.uptime=505
eq(assert(lifecycle.step(runner,505,provider)).status,
   "sample_accepted","post_restart_pon_sample")
provider.uptime=565
local after=assert(lifecycle.step(runner,565,provider))
eq(after.has_rate,true,"post_restart_actual_byte_counters")
local fresh_history=assert(lifecycle.history(runner,"hour"))
eq(#fresh_history.samples,3,"volatile_history_restarted_not_faked")
eq(fresh_history.windows.hour.rx.covered_seconds,120,
   "new_era_rates_not_merged_with_closed_collector")
-- Device monotonic clock regression is not enough to declare a reboot;
-- only a changed boot UUID returned by the guarded native reader is.
provider.uptime=2
local wrong,clock_error=lifecycle.step(runner,2,provider)
eq(wrong,nil,"rewind_same_boot_not_accepted")
eq(clock_error,"collector_clock_regressed","rewind_error_code")
eq(assert(lifecycle.status(runner)).running,true,
   "clock_rejection_does_not_release_proven_owner")
provider.boot=BOOT_RESTART
local restarted=assert(lifecycle.step(runner,2,provider))
eq(restarted.status,"sample_accepted","new_boot_accepted_after_verification")
eq(restarted.history_status,"reboot","new_boot_marker")
eq(restarted.has_rate,false,"new_boot_no_counter_continuity")
local new_boot_history=assert(lifecycle.history(runner,"hour"))
eq(#new_boot_history.samples,1,"reboot_epoch_not_crossed")
eq(new_boot_history.events[1].kind,"reboot_observed",
   "verified_reboot_recorded")
eq(assert(lifecycle.stop(runner)).phase,"stopped","operator_stop")
eq(assert(lifecycle.step(runner,600,provider)).status,
   "stopped_no_auto_start","operator_stop_does_not_reschedule")
local finished=assert(lifecycle.shutdown(runner))
eq(finished.phase,"closed","closed_lifecycle")
eq(finished.running,false,"closed_no_kernel_owner")
local invalid_start,reason=lifecycle.start(runner,605)
eq(invalid_start,nil,"cannot_restart_closed_session")
eq(reason,"lifecycle_not_restartable","closed_error")
eq(lifecycle.shutdown(runner),nil,"double_shutdown_refused")

-- Unsafe lock directories fail closed with no retry or background action.
local unsafe=assert(lifecycle.new("/var/tmp/unapproved",
    settings,capabilities,"offline_synthetic"))
local failed,why=lifecycle.start(unsafe,100)
eq(failed,nil,"unsafe_directory_no_start")
eq(why,"disallowed_lock_directory","unsafe_directory_reason")
eq(assert(lifecycle.status(unsafe)).phase,"unsafe",
   "unsafe_failure_cannot_spin")
eq(lifecycle.start(unsafe,160),nil,"unsafe_not_restartable")
eq(lifecycle.shutdown(unsafe),nil,"unsafe_shutdown_refused")

-- Strict session restart budget. Repeated read failures eventually
-- open a circuit breaker requiring a new, explicit source session.
local bounded=assert(lifecycle.new(directory,settings,capabilities,
                                    "offline_synthetic"))
local now=1000
local error_provider=fake()
error_provider.boot_invalid=true
for epoch=1,4 do
    local started=assert(lifecycle.start(bounded,now))
    eq(started.phase,"running","epoch_"..epoch.."_started")
    for j=1,4 do
        error_provider.uptime=now
        local value=assert(lifecycle.step(bounded,now,error_provider))
        if j<4 then
            eq(value.status,"reader_backoff",
               "epoch_"..epoch.."_reader_backoff_"..j)
            now=value.next_collector_uptime
        else
            eq(value.restart_count,epoch,
               "epoch_"..epoch.."_controlled_restart_counter")
            if epoch==4 then
                eq(value.status,"circuit_open","no_unbounded_restarts")
                eq(value.circuit_open,true,"circuit_open_ack")
            else
                eq(value.status,"cooldown","bounded_restart_delay")
                now=value.next_start_uptime
            end
        end
    end
end
local breaker=assert(lifecycle.status(bounded))
eq(breaker.phase,"circuit_open","tripped_source_session")
eq(breaker.owns_kernel_lock,false,"breaker_released_kernel_lock")
eq(breaker.restart_count,4,"explicit_restart_budget_exhausted")
eq(assert(lifecycle.stop(bounded)).phase,"circuit_open",
   "stop_cannot_reset_breaker")
local blocked,blocked_reason=lifecycle.start(bounded,now+999)
eq(blocked,nil,"circuit_cannot_restart")
eq(blocked_reason,"lifecycle_not_restartable","breaker_error")
eq(assert(lifecycle.shutdown(bounded)).phase,"closed",
   "explicit_shutdown_allowed")

ok(checks>=100,"full_lifecycle_fixture")
print("AOTT_H023_LIFECYCLE_FIXTURE_PASS checks="..checks)
