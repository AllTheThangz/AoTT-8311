-- H-020: single-owner bounded offline source collector, no hardware access.
local root=assert(arg[1],"Prototype library root required")
local overlay=assert(arg[2],"Overlay model root required")
package.path=root.."/?.lua;"..overlay.."/?.lua;"..package.path
local collector=require "8311.history_collector"
local preferences=require "8311.history_preferences"
local checks=0
local function ok(v,label)
    checks=checks+1
    assert(v,"H020_COLLECTOR_FIXTURE_FAILED:"..label)
end
local function eq(a,b,label) ok(a==b,label) end
local synthetic_profile={kind="source_only",native_qualified=true,
    optics_qualified=false,storage_qualified=false,alerts_qualified=false}
local inactive=preferences.defaults()
local source_profile=preferences.source_profile()
local disabled=assert(collector.new(inactive,source_profile))
local disabled_status=assert(collector.status(disabled))
eq(disabled_status.enabled,false,"disabled_is_default")
eq(disabled_status.no_timer_or_background_process,true,"no_hidden_scheduler")
eq(disabled_status.no_flash_write,true,"no_flash")
local disabled_tick=assert(collector.tick(disabled,100,nil))
eq(disabled_tick.status,"disabled","disabled_no_provider")
eq(disabled_tick.no_native_probe,true,"disabled_skips_native")
local empty=assert(collector.view(disabled,"hour"))
eq(#empty.samples,0,"disabled_no_samples")
eq(assert(collector.close(disabled)).status,"closed","close_inactive")
eq(collector.status(disabled),nil,"closed_handle_invalid")

local settings=assert(preferences.simulate(inactive,
    {sampling_enabled=true},1,synthetic_profile))
local denied,reason=collector.new(settings,source_profile,"offline_synthetic")
eq(denied,nil,"unqualified_profile_refused")
eq(reason,"hardware_not_directly_qualified","unqualified_profile_error")
denied,reason=collector.new(settings,synthetic_profile)
eq(denied,nil,"missing_explicit_synthetic_mode_refused")
eq(reason,"hardware_not_directly_qualified","missing_mode_error")
local active=assert(collector.new(settings,synthetic_profile,"offline_synthetic"))
local another,owner_error=collector.new(settings,synthetic_profile,"offline_synthetic")
eq(another,nil,"only_one_active_handle")
eq(owner_error,"collector_owner_exists","single_process_owner")
local status=assert(collector.status(active))
eq(status.status,"offline_synthetic_only","active_remains_offline")
eq(status.one_shared_native_sample_interval_seconds,60,"shared_60s")
eq(status.independent_channel_cadences_implemented,false,
   "no_false_independent_cadence")
eq(status.no_live_firmware_integration,true,"no_live_integration")
eq(status.no_device_write,true,"no_device_writes")
eq(status.retained_samples,0,"nothing_collected_yet")

local PON="/usr/bin/timeout -k 1 3 /usr/bin/pon psg"
local ETH="/usr/bin/timeout -k 1 4 /usr/sbin/ethtool -S eth0_0"
local BOOT_A="11111111-2222-4333-8444-555555555555"
local BOOT_B="22222222-3333-4444-8555-666666666666"
local function fake(options)
    options=options or {}
    local p={calls=0,reads=0,uptime=100,boot=BOOT_A,
      pon_exit=nil,eth_exit=nil,link_missing=false,read_error=false,
      pon_state=51,raise_run=false,eth_missing=false,
      boot_invalid=false,reentrant=nil,read_reenter=false,
      inner_reason=nil}
    function p.read(path,max)
        p.reads=p.reads+1
        if p.read_reenter and not p.inner_reason then
            local nested,why=collector.tick(active,p.uptime,p)
            eq(nested,nil,"reentrant_call_blocked")
            p.inner_reason=why
        end
        if p.read_error then error("synthetic_read_fault") end
        if path=="/proc/sys/kernel/random/boot_id" then
            eq(max,80,"bounded_boot_read")
            return p.boot_invalid and "bad" or p.boot.."\n"
        elseif path=="/proc/uptime" then
            eq(max,80,"bounded_uptime_read")
            return string.format("%.2f 12.00\n",p.uptime)
        elseif path=="/sys/class/net/eth0_0/speed" then
            eq(max,32,"bounded_host_link")
            if p.link_missing then return nil end
            return "10000\n"
        end
        error("unexpected_test_kernel_read")
    end
    function p.run(argv,max)
        p.calls=p.calls+1
        local cmd=table.concat(argv," ")
        if p.raise_run then error("synthetic_native_process_exception") end
        if cmd==PON then
            eq(max,1024,"bounded_pon_report")
            return p.pon_exit or 0,
                "current="..tostring(p.pon_state).."\n",false
        elseif cmd==ETH then
            eq(max,16384,"bounded_eth_report")
            if p.eth_missing then return 1,"",false end
            local count=math.floor(p.uptime*1250000)
            return p.eth_exit or 0,
                "RxGoodBytes: "..tostring(count)..
                "\nTxGoodBytes: "..tostring(count*2).."\n",false
        end
        error("unexpected_test_native_process")
    end
    for k,v in pairs(options) do p[k]=v end
    return p
end

local provider=fake()
local first=assert(collector.tick(active,100,provider))
eq(first.status,"sample_accepted","first_sample")
eq(first.history_status,"baseline","first_is_baseline")
eq(first.has_rate,false,"first_has_no_rate")
eq(provider.calls,2,"one_pon_one_ethernet")
eq(assert(collector.status(active)).samples_accepted,1,"first_retained")
local next=assert(collector.tick(active,101,provider))
eq(next.status,"not_due","no_excessive_polling")
eq(next.next_due_uptime,160,"next_due_160")
eq(provider.calls,2,"early_tick_no_subprocess")
next=assert(collector.tick(active,159,provider))
eq(next.no_native_probe,true,"59s_no_native")
provider.uptime=160
local second=assert(collector.tick(active,160,provider))
eq(second.history_status,"valid_interval","second_interval")
eq(second.has_rate,true,"counter_delta_calculated")
eq(provider.calls,4,"two_cycles_four_commands")
local page=assert(collector.view(active,"hour"))
eq(#page.samples,2,"two_samples_in_history")
eq(page.source_only_not_live,true,"history_is_preview")
eq(page.actual_isp_uptime_unverified,true,"history_no_WAN_inference")
local rates=page.windows.hour
ok(rates.rx.average_mbps>0,"measured_rx_available")
ok(rates.tx.average_mbps>0,"measured_tx_available")
ok(page.samples[2].boot==nil,"boot_not_in_export")
ok(page.samples[2].eth==nil,"raw_counter_not_exported")
local doc=assert(collector.export_json(active,"hour"))
ok(doc:find('"samples":[',1,true)~=nil,"safe_json_available")
ok(doc:find(BOOT_A,1,true)==nil,"boot_UUID_not_exported")
local csv=assert(collector.export_csv(active,"hour"))
ok(csv:find("record_type,at_uptime",1,true)~=nil,
   "safe_CSV_available")
ok(csv:find(BOOT_A,1,true)==nil,"CSV_does_not_export_boot_UUID")

provider.uptime=220
provider.pon_exit=1
local partial=assert(collector.tick(active,220,provider))
eq(partial.status,"sample_accepted","partial_observation_accepted")
eq(partial.availability.pon,"unavailable","PON_explicit_unknown")
eq(partial.availability.host_counters,"observed",
   "Ethernet_still_measured")
eq(partial.history_status,"observation_unavailable",
   "partial_not_false_PON_down")
provider.pon_exit=nil
provider.uptime=280
local restored=assert(collector.tick(active,280,provider))
eq(restored.status,"sample_accepted","recovered_native_observation")
eq(restored.has_rate,false,"partial_interval_breaks_rate_baseline")
provider.uptime=340
local subsequent=assert(collector.tick(active,340,provider))
eq(subsequent.has_rate,true,"rates_resume_after_baseline")

-- Failed kernel identity terminates before either native process.
provider.uptime=400
provider.boot_invalid=true
local before_fail=provider.calls
local failure=assert(collector.tick(active,400,provider))
eq(failure.status,"retry_scheduled","bad_boot_retry")
eq(failure.retry_after_seconds,15,"first_retry_15")
eq(failure.last_error,"boot_identity_unavailable","bounded_error")
eq(provider.calls,before_fail,"bad_boot_no_native_command")
local delayed=assert(collector.tick(active,410,provider))
eq(delayed.status,"not_due","not_due_during_backoff")
eq(provider.calls,before_fail,"backoff_no_process")
provider.uptime=415
local second_error=assert(collector.tick(active,415,provider))
eq(second_error.retry_after_seconds,30,"second_retry_30")
provider.uptime=445
local third_error=assert(collector.tick(active,445,provider))
eq(third_error.retry_after_seconds,60,"third_retry_60")
provider.uptime=505
local fourth_error=assert(collector.tick(active,505,provider))
eq(fourth_error.retry_after_seconds,120,"fourth_retry_120")
provider.uptime=625
local fifth_error=assert(collector.tick(active,625,provider))
eq(fifth_error.retry_after_seconds,300,"fifth_retry_capped_300")
provider.uptime=925
local sixth_error=assert(collector.tick(active,925,provider))
eq(sixth_error.retry_after_seconds,300,"repeated_failure_backoff_capped")
eq(assert(collector.status(active)).consecutive_failures,5,
    "bounded_failure_streak")
provider.boot_invalid=false
provider.uptime=1225
local success=assert(collector.tick(active,1225,provider))
eq(success.status,"sample_accepted","recovered_after_backoff")
eq(assert(collector.status(active)).consecutive_failures,0,
   "backoff_reset_on_success")
eq(assert(collector.status(active)).last_error,nil,"cleared_error")

-- Cross-process locks and automatic service supervisors are NOT present.
-- Even for a trusted synthetic mode, this interface does not create one.
provider.uptime=1285
provider.read_reenter=true
local nested=assert(collector.tick(active,1285,provider))
eq(nested.status,"sample_accepted","outer_reentrant_still_completes")
eq(provider.inner_reason,"native_probe_already_in_flight",
   "single_owner_reentrancy_guard")
provider.read_reenter=false
local backwards,clockreason=collector.tick(active,1284,provider)
eq(backwards,nil,"clock_regression_rejected")
eq(clockreason,"collector_clock_regressed","clock_regression_reason")
local clockinvalid=collector.tick(active,0/0,provider)
eq(clockinvalid,nil,"nan_clock_rejected")
local invalid_provider=collector.tick(active,1345,nil)
eq(invalid_provider,nil,"missing_provider_refused_when_due")
eq(assert(collector.status(active)).samples_accepted,7,
   "no_ingest_for_bad_provider")

-- Complete native unavailability cannot be reclassified as a verified
-- fiber outage or a zero host throughput value.
provider.uptime=1345
provider.pon_exit=1
provider.link_missing=true
provider.eth_missing=true
local complete=assert(collector.tick(active,1345,provider))
eq(complete.status,"retry_scheduled","all_missing_schedules_retry")
eq(complete.last_error,"no_valid_native_measurement","no_false_loss")
eq(assert(collector.status(active)).samples_accepted,7,
   "all_missing_did_not_store_fake_disconnection")
provider.pon_exit=nil
provider.link_missing=false
provider.eth_missing=false

local old=assert(collector.status(active))
eq(old.one_shared_native_sample_interval_seconds,60,"requested_interval")
eq(old.no_timer_or_background_process,true,"no_internal_loop")
ok(old.failed_attempts>=7,"counted_failures")
ok(old.calls>old.samples_accepted,"attempts_include_failed_reads")
eq(assert(collector.close(active)).status,"closed","active_closed")
eq(collector.tick(active,1400,provider),nil,"closed_handle_no_polling")
local restarted=assert(collector.new(settings,synthetic_profile,"offline_synthetic"))
eq(assert(collector.status(restarted)).retained_samples,0,
   "new_process_state_starts_empty")
assert(collector.close(restarted))

-- Differing PON/Ethernet requested intervals are a real feature gap.
-- Reject them rather than silently running an unexpected cadence.
local mixed=assert(preferences.simulate(inactive,{
    sampling_enabled=true,pon_interval_seconds=120,
    host_interval_seconds=60,
},1,synthetic_profile))
local rejected,why=collector.new(mixed,synthetic_profile,"offline_synthetic")
eq(rejected,nil,"no_fake_separate_interval_scheduling")
eq(why,"independent_channel_cadences_not_yet_implemented",
   "clear_missing_feature_error")
local too_fast=assert(preferences.simulate(inactive,{
    sampling_enabled=true,pon_interval_seconds=30,host_interval_seconds=60,
},1,synthetic_profile))
rejected,why=collector.new(too_fast,synthetic_profile,"offline_synthetic")
eq(rejected,nil,"mixed_fast_not_implemented")
eq(why,"independent_channel_cadences_not_yet_implemented",
   "no_unqualified_half_frequency")
local unsupported=assert(preferences.simulate(inactive,{
    persist_enabled=false,retention_days=0,local_alerts_enabled=false,
    pon_interval_seconds=120,
},1,synthetic_profile))
eq(unsupported.values.persist_enabled,false,"no_persistent_side_effect")
-- During a sustained partial native failure the collector preserves
-- valid host observations without filling the bounded event ring with
-- identical "unavailable" notices. Real changes still become events.
local sustained=assert(collector.new(settings,synthetic_profile,"offline_synthetic"))
local degraded=fake({pon_exit=1})
for i=0,99 do
    degraded.uptime=2000+i*60
    local observation=assert(collector.tick(sustained,degraded.uptime,degraded))
    eq(observation.status,"sample_accepted","degraded_sample_"..i)
    eq(observation.history_status,"observation_unavailable",
        "partial_not_fake_pon_outage_"..i)
    eq(observation.availability.pon,"unavailable",
        "native_PON_missing_"..i)
end
local measured=assert(collector.status(sustained))
eq(measured.retained_samples,100,"sustained_partial_samples_retained")
eq(measured.retained_events,1,"sustained_partial_one_event_only")
eq(measured.samples_accepted,100,"all_partial_samples_accepted")
degraded.pon_exit=nil
degraded.uptime=8000
local baseline=assert(collector.tick(sustained,8000,degraded))
eq(baseline.events_added,0,"PON_restore_not_fabricated_recovery")
degraded.uptime=8060
degraded.pon_state=60
local changed=assert(collector.tick(sustained,8060,degraded))
eq(changed.events_added,1,"real_PON_change_recorded")
degraded.uptime=8120
degraded.pon_exit=1
local again=assert(collector.tick(sustained,8120,degraded))
eq(again.events_added,1,"new_PON_probe_failure_once")
eq(assert(collector.status(sustained)).retained_events,3,
    "events_are_two_unknown_epochs_and_one_real_transition")
local recent=assert(collector.view(sustained,"hour"))
eq(recent.samples[#recent.samples].pon_observation,"unavailable",
   "most_recent_PON_is_explicit_unknown")
eq(recent.actual_isp_uptime_unverified,true,"no_ISP_fault_claim")
assert(collector.close(sustained))

ok(checks>=400,"fixture_sufficiently_complete")
print("AOTT_H020_SINGLE_COLLECTOR_FIXTURE_PASS checks="..checks)
