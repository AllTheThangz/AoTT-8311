-- H-021: independent PON/host sampling, exact counter clocks and privacy.
-- Synthetic fixed native outputs only, no active PRX126 commands.
local root=assert(arg[1],"Prototype root")
local overlay=assert(arg[2],"Overlay root")
package.path=root.."/?.lua;"..overlay.."/?.lua;"..package.path
local prefs=require "8311.history_preferences"
local probe=require "8311.history_native_probe"
local collector=require "8311.history_collector"
local checked=0
local function ok(value,name)
    checked=checked+1
    assert(value,"H021_CHANNEL_FIXTURE_FAILED:"..name)
end
local function eq(a,b,name) ok(a==b,name) end
local BOOT_A="11111111-2222-4333-8444-555555555555"
local BOOT_B="22222222-3333-4444-8555-666666666666"
local PON="/usr/bin/timeout -k 1 3 /usr/bin/pon psg"
local ETH="/usr/bin/timeout -k 1 4 /usr/sbin/ethtool -S eth0_0"
local profile={kind="source_only",native_qualified=true}
local function build(p,t)
    local state=assert(prefs.defaults())
    local updated,why=prefs.simulate(state,{
        sampling_enabled=true,pon_interval_seconds=p,
        host_interval_seconds=t,
    },1,profile)
    if not updated then return nil,why end
    return updated
end
local function fake()
    local p={uptime=100,pon_state=51,boot=BOOT_A,pon_exit=0,
             eth_exit=0,commands={},reads={},reenter=false,
             reenter_reason=nil,collector_handle=nil}
    function p.read(path,limit)
        p.reads[#p.reads+1]=path
        if p.reenter and not p.reenter_reason then
            local duplicate,why=collector.tick(p.collector_handle,p.uptime,p)
            eq(duplicate,nil,"overlap_rejected")
            p.reenter_reason=why
        end
        if path=="/proc/sys/kernel/random/boot_id" then
            eq(limit,80,"boot_output_limit")
            return p.boot.."\n"
        end
        if path=="/proc/uptime" then
            eq(limit,80,"uptime_output_limit")
            return tostring(p.uptime).." 18.0\n"
        end
        if path=="/sys/class/net/eth0_0/speed" then
            eq(limit,32,"link_output_limit")
            return "10000\n"
        end
        error("Unexpected selected kernel read")
    end
    function p.run(argv,limit)
        local command=table.concat(argv," ")
        p.commands[#p.commands+1]=command
        if command==PON then
            eq(limit,1024,"PON_output_cap")
            return p.pon_exit,
                "current="..tostring(p.pon_state).."\n",false
        elseif command==ETH then
            eq(limit,16384,"ETH_output_cap")
            local rx=math.floor(p.uptime*1250000)
            return p.eth_exit,
                "RxGoodBytes: "..tostring(rx)..
                "\nTxGoodBytes: "..tostring(rx*2).."\n",false
        end
        error("Unexpected selected native process")
    end
    return p
end
local par=fake()
local before_reads=#par.reads
local s,why=probe.read_selected(par,{pon=false,host=false})
eq(s,nil,"empty_selection_denied")
eq(why,"invalid_probe_selection","empty_selection_reason")
s,why=probe.read_selected(par,{pon=1,host=true})
eq(s,nil,"not_boolean_selection_denied")
s,why=probe.read_selected(par,{pon=true,host=false,extra=true})
eq(s,nil,"unknown_selection_key_denied")
eq(#par.reads,before_reads,"bad_selection_no_kernel_read")
local snap,available=assert(probe.read_selected(par,{pon=true,host=false}))
eq(#par.commands,1,"PON_only_one_command")
eq(par.commands[1],PON,"PON_only_fixed_argv")
eq(available.pon,"observed","PON_observed")
eq(available.host_link,"not_sampled","host_not_sampled")
eq(available.host_counters,"not_sampled","counters_not_sampled")
eq(snap.observed.pon,true,"PON_attempted")
eq(snap.observed.host,false,"host_not_attempted")
eq(snap.ethernet_mbps,nil,"host_speed_not_cached")
eq(snap.eth.RxGoodBytes,nil,"host_counters_not_cached")
eq(#par.reads,4,"PON_only_boot_uptime_twice")
par.commands={};par.reads={}
snap,available=assert(probe.read_selected(par,{pon=false,host=true}))
eq(#par.commands,1,"host_only_one_command")
eq(par.commands[1],ETH,"host_only_fixed_argv")
eq(available.pon,"not_sampled","PON_not_sampled")
eq(available.host_link,"observed","host_link_observed")
eq(available.host_counters,"observed","host_counters_observed")
eq(snap.pon_state,nil,"PON_not_cached")
eq(snap.observed.pon,false,"PON_not_attempted")
eq(#par.reads,5,"host_only_boot_uptime_twice_plus_speed")

local mixed=assert(build(60,120))
local disabled=collector.new_independent(mixed,prefs.source_profile(),"offline_synthetic")
eq(disabled,nil,"unqualified_mode_cannot_enable")
local missing,why=collector.new_independent(mixed,profile)
eq(missing,nil,"missing_synthetic_gate_rejected")
eq(why,"hardware_not_directly_qualified","hardware_gate_explicit")
local active=assert(collector.new_independent(mixed,profile,"offline_synthetic"))
par=fake();par.collector_handle=active;par.commands={};par.reads={}
local another,owner=collector.new(mixed,profile,"offline_synthetic")
eq(another,nil,"combined_constructor_rejects_mixed")
local other,owner_reason=collector.new_independent(mixed,profile,"offline_synthetic")
eq(other,nil,"one_owner_across_collector_modes")
eq(owner_reason,"collector_owner_exists","process_local_singleton")
local meta=assert(collector.status(active))
eq(meta.independent_channel_cadences_implemented,true,"independent_mode_true")
eq(meta.pon_interval_seconds,60,"PON_60")
eq(meta.host_interval_seconds,120,"host_120")
eq(meta.one_shared_native_sample_interval_seconds,nil,"no_fake_single_interval")
local function tick(t)
    par.uptime=t
    return assert(collector.tick(active,t,par))
end
local result=tick(100)
eq(result.due_pon,true,"initial_PON_due")
eq(result.due_host,true,"initial_host_due")
eq(#par.commands,2,"both_probes_initial")
eq(result.history_status,"baseline","first_measured_baseline")
eq(result.has_rate,false,"first_no_rate")
eq(result.next_due_uptime,160,"first_next_due_min")
eq(result.pon_next_due_uptime,160,"PON_next_60")
eq(result.host_next_due_uptime,220,"host_next_120")
local idle=assert(collector.tick(active,159,par))
eq(idle.status,"not_due","early_tick_refused")
eq(#par.commands,2,"early_no_process")
result=tick(160)
eq(result.due_pon,true,"60_PON_due")
eq(result.due_host,false,"60_host_skipped")
eq(result.availability.host_counters,"not_sampled","host_not_failed")
eq(#par.commands,3,"PON_only_one_extra_native_call")
eq(par.commands[3],PON,"only_PON_called")
eq(result.history_status,"partial_interval","PON_only_partial")
eq(result.has_rate,false,"PON_only_not_zero_rate")
local tail=assert(collector.view(active,"hour"))
eq(tail.samples[#tail.samples].host_link_observation,"not_sampled",
   "host_not_sampled_in_export")
eq(tail.samples[#tail.samples].rx_mbps,nil,"no_stale_speed_value")
eq(tail.events[#tail.events] and tail.events[#tail.events].kind,nil,
   "no_false_host_failure")
result=tick(220)
eq(result.due_pon,true,"120_PON_due")
eq(result.due_host,true,"120_host_due")
eq(#par.commands,5,"two_more_native_calls")
eq(result.history_status,"valid_interval","combined_elapsed_valid")
eq(result.has_rate,true,"counter_rate_across_PON_only_sample")
tail=assert(collector.view(active,"hour"))
local latest=tail.samples[#tail.samples]
eq(latest.elapsed_seconds,120,"exact_120_sec_counter_interval")
ok(math.abs(latest.rx_mbps-10)<0.000001,"RX_10mbps_from_real_counter_pair")
ok(math.abs(latest.tx_mbps-20)<0.000001,"TX_20mbps_from_real_counter_pair")
eq(tail.windows.hour.rx.interval_count,1,"one_exact_counter_interval")
eq(tail.windows.hour.unavailable_host_samples,0,
   "skipped_host_not_marked_failed")
eq(tail.windows.hour.unavailable_pon_samples,0,
   "scheduled_PON_not_marked_failed")
eq(tail.windows.hour.rx.covered_seconds,120,
   "coverage_elapsed_between_true_host_reads")

par.pon_state=60
result=tick(280)
eq(result.due_pon,true,"180_PON_due")
eq(result.due_host,false,"180_host_skipped")
eq(result.events_added,1,"true_PON_transition")
tail=assert(collector.view(active,"hour"))
eq(tail.events[#tail.events].kind,"pon_state_change","PON_change_kind")
eq(tail.events[#tail.events].from,51,"true_prior_PON_state")
eq(tail.events[#tail.events].to,60,"true_new_PON_state")
eq(tail.events[#tail.events].observation_window_seconds,60,
   "PON_window_between_true_PON_samples")
result=tick(340)
eq(result.has_rate,true,"host_counter_rate_after_PON_only_change")
tail=assert(collector.view(active,"hour"))
eq(tail.samples[#tail.samples].elapsed_seconds,120,
   "second_host_counter_elapsed_120")
eq(#par.commands,8,"2_both_2_PON_only_commands")

-- Simulated failure of a PON-only probe: schedule bounded retry,
-- no fabricated PON state, and no host counter reset if not probed.
par.pon_exit=1
result=tick(400)
eq(result.status,"retry_scheduled","PON_only_failed_retry")
eq(result.retry_after_seconds,15,"first_retry_15")
eq(assert(collector.status(active)).samples_accepted,5,
   "failed_only_channel_not_ingested")
local oldcalls=#par.commands
idle=assert(collector.tick(active,410,par))
eq(idle.status,"not_due","retry_hold")
eq(#par.commands,oldcalls,"retry_hold_no_process")
par.pon_exit=0
result=tick(415)
eq(result.due_pon,true,"retry_PON_due")
eq(result.due_host,false,"host_not_force_polled_during_PON_retry")
eq(result.has_rate,false,"PON_only_retry_no_traffic_rate")
result=tick(460)
eq(result.due_pon,false,"460_PON_not_due")
eq(result.due_host,true,"460_host_due")
eq(result.availability.pon,"not_sampled","skipped_PON_not_down")
eq(result.has_rate,true,"host_rate_from_last_real_host_counter")
tail=assert(collector.view(active,"hour"))
eq(tail.samples[#tail.samples].elapsed_seconds,120,
   "third_host_rate_120_no_fake_intervening_zero")
eq(tail.samples[#tail.samples].pon_observation,"not_sampled",
   "WAN_export_honors_partial_source")
eq(tail.actual_isp_uptime_unverified,true,"not_claimed_connected_to_ISP")
local csv=assert(collector.export_csv(active,"hour"))
ok(not csv:find(BOOT_A,1,true),"boot_uuid_private_in_CSV")
local json=assert(collector.export_json(active,"hour"))
ok(json:find('"not_sampled"',1,true)~=nil,"JSON_records_not_sampled")
ok(not json:find(BOOT_A,1,true),"no_boot_uuid_in_JSON")
local selected_json=json
-- A real reboot resets uptime. Only a separately observed, changed
-- kernel boot UUID may reset the collector's monotonic schedule.
par.uptime=5
local previous=assert(collector.status(active)).samples_accepted
local denied_reboot,denied_reason=collector.tick(active,5,par)
eq(denied_reboot,nil,"clock_rewind_same_boot_rejected")
eq(denied_reason,"collector_clock_regressed",
   "unchanged_boot_does_not_rewind")
eq(assert(collector.status(active)).samples_accepted,previous,
   "same_boot_rewind_no_sample_mutation")
par.boot=BOOT_B
local real_reboot=assert(collector.tick(active,5,par))
eq(real_reboot.history_status,"reboot","verified_boot_reinitializes")
eq(real_reboot.has_rate,false,"reboot_no_cross_boot_throughput")
eq(real_reboot.due_pon,true,"reboot_PON_initial_due")
eq(real_reboot.due_host,true,"reboot_host_initial_due")
eq(real_reboot.pon_next_due_uptime,65,"new_boot_PON_schedule")
eq(real_reboot.host_next_due_uptime,125,"new_boot_host_schedule")
local new_epoch=assert(collector.view(active,"ninety_days"))
eq(#new_epoch.samples,1,"no_prior_boot_rows_in_history_view")
eq(new_epoch.events[1].kind,"reboot_observed",
   "real_reboot_recorded_only_after_boot_uuid_change")
eq(new_epoch.samples[1].epoch_index,2,"new_boot_epoch")
eq(new_epoch.actual_isp_uptime_unverified,true,
   "reboot_does_not_claim_ISP_outage_or_uptime")
result=tick(65)
eq(result.due_pon,true,"new_boot_PON_only_65")
eq(result.due_host,false,"new_boot_host_skipped_65")
result=tick(125)
eq(result.due_pon,true,"new_boot_PON_due_125")
eq(result.due_host,true,"new_boot_host_due_125")
eq(result.has_rate,true,"new_boot_rate_from_two_genuine_counters")
new_epoch=assert(collector.view(active,"hour"))
eq(new_epoch.samples[#new_epoch.samples].elapsed_seconds,120,
   "new_boot_host_120_sec_rate")
eq(assert(collector.status(active)).consecutive_failures,0,
   "reboot_restores_healthy_sampler")

eq(assert(collector.close(active)).status,"closed","close_independent_owner")

-- PON-30/host-60 and PON-60/host-30 each schedule one channel on
-- alternate ticks, not double-spawning expensive subprocesses.
for _,intervals in ipairs({{30,60},{60,30},{120,300},{300,120}}) do
    local configured=assert(build(intervals[1],intervals[2]))
    local owner_handle=assert(collector.new_independent(
        configured,profile,"offline_synthetic"))
    local f=fake()
    f.uptime=100
    local sample1=assert(collector.tick(owner_handle,100,f))
    eq(sample1.due_pon,true,"first_both_due_"..intervals[1]..intervals[2])
    eq(sample1.due_host,true,"first_host_due_"..intervals[1]..intervals[2])
    local earliest=100+math.min(intervals[1],intervals[2])
    f.uptime=earliest
    local sample2=assert(collector.tick(owner_handle,earliest,f))
    eq(sample2.due_pon,intervals[1]==math.min(intervals[1],intervals[2]),
       "second_PON_exact_cadence_"..intervals[1]..intervals[2])
    eq(sample2.due_host,intervals[2]==math.min(intervals[1],intervals[2]),
       "second_host_exact_cadence_"..intervals[1]..intervals[2])
    eq(#f.commands,3,"only_one_due_channel_process")
    eq(assert(collector.status(owner_handle)).samples_accepted,2,
       "two_valid_selected_observations")
    assert(collector.close(owner_handle))
end
-- A failed scheduled PON read at a valid host tick is not the same
-- as an intentionally skipped PON. It breaks rate continuity safely.
local partial_profile=assert(build(60,30))
local partial_owner=assert(collector.new_independent(
    partial_profile,profile,"offline_synthetic"))
local failing=fake()
failing.uptime=100
local a=assert(collector.tick(partial_owner,100,failing))
eq(a.history_status,"baseline","partial_first_baseline")
failing.uptime=130
a=assert(collector.tick(partial_owner,130,failing))
eq(a.has_rate,true,"host_only_30s_rate")
eq(a.availability.pon,"not_sampled","PON_skipped_not_failed")
failing.uptime=160
failing.pon_exit=1
a=assert(collector.tick(partial_owner,160,failing))
eq(a.status,"sample_accepted","valid_host_keeps_partial_observation")
eq(a.history_status,"observation_unavailable",
   "actual_failed_PON_is_unavailable")
eq(a.has_rate,false,"failed_PON_prevents_unjustified_rate")
eq(a.availability.pon,"unavailable","PON_due_and_failed")
eq(a.events_added,1,"one_real_missing_probe_event")
failing.uptime=190
failing.pon_exit=0
a=assert(collector.tick(partial_owner,190,failing))
eq(a.availability.pon,"not_sampled","PON_not_called_at_190")
eq(a.has_rate,false,"first_host_after_failed_PON_is_baseline")
failing.uptime=220
a=assert(collector.tick(partial_owner,220,failing))
eq(a.has_rate,true,"host_rates_restart_after_failure_baseline")
local partial_view=assert(collector.view(partial_owner,"hour"))
eq(partial_view.samples[3].pon_observation,"unavailable",
   "failure_is_not_a_skip")
eq(partial_view.samples[4].pon_observation,"not_sampled",
   "skip_is_not_a_failure")
eq(partial_view.windows.hour.unavailable_pon_samples,1,
   "only_true_probing_failure_counted")
assert(collector.close(partial_owner))
local unimplemented_optical=assert(prefs.simulate(
    prefs.defaults(),{sampling_enabled=true,optical_interval_seconds=60},
    1,profile))
local o,oe=collector.new_independent(unimplemented_optical,profile,
    "offline_synthetic")
eq(o,nil,"unsupported_optical_interval_rejected")
eq(oe,"optical_cadence_not_implemented",
   "optical_polling_not_silently_ignored")

local unsafe={schema=1,revision=2,source_only_not_live=true,no_device_write=true,
 values={sampling_enabled=true,pon_interval_seconds=30,
         host_interval_seconds=30,optical_interval_seconds=120,
         ram_sample_limit=120,
         ram_event_limit=128,heavy_probe_seconds=0,
         persist_enabled=false,local_alerts_enabled=false,
         remote_notifications=false,retention_days=0}}
local impossible,err=collector.new_independent(
    unsafe,profile,"offline_synthetic")
eq(impossible,nil,"30_30_exceeds_native_budget")
eq(err,"collector_interval_not_qualified","unsafe_30_30_reason")
ok(checked>=175,"fixture_complete")
print("AOTT_H021_INDEPENDENT_CADENCE_FIXTURE_PASS checks="..checked)
if arg[3]=="emit_json" then
    print("AOTT_H021_SELECTED_JSON="..selected_json)
end
