-- H-012: independent PON and host-link measurement availability.
-- Pure synthetic fixture. No ONU, sockets, native processes or file writes.
local root=assert(arg[1], "Prototype library root required")
package.path=root.."/?.lua;"..package.path
local sampler=require "8311.history_sampler"
local checks=0
local function verify(ok,reason)
    checks=checks+1
    assert(ok, "H012_CHANNEL_FIXTURE_FAILED:"..reason)
end
local function eq(a,b,reason) verify(a==b,reason) end
local function item(boot,uptime,pon,link,source)
    return {
        boot=boot,uptime=uptime,pon_state=pon,ethernet_mbps=link,
        source=source or "eth0_0",
        eth={RxGoodBytes=tostring(uptime*100),TxGoodBytes=tostring(uptime*200)},
        registration_credential="SYNTHETIC_NOT_FOR_EXPORT"
    }
end
local state=assert(sampler.new({max_samples=16,max_events=16}))
local function feed(input)
    local receipt,err=sampler.ingest(state,input)
    verify(receipt~=nil,err or "valid_ingest")
    return receipt
end
local function recent()
    return assert(sampler.recent(state,"events",16))
end
local function last_event()
    local list=recent()
    return list[#list]
end

local result=feed(item("boot-A",10,51,10000))
eq(result.status,"baseline","initial_baseline")
eq(result.events_added,0,"initial_no_event")
eq(result.has_rate,false,"initial_no_rate")

-- PON reports a real state transition even if the host speed probe fails.
result=feed(item("boot-A",20,60,nil))
eq(result.status,"observation_unavailable","missing_host_classified")
eq(result.has_rate,false,"missing_host_no_rate")
eq(result.events_added,2,"pon_transition_and_host_unavailable")
local events=recent()
eq(#events,2,"two_observed_events")
eq(events[1].kind,"pon_state_change","pon_transition_survives_host_probe_failure")
eq(events[1].from,51,"pon_before")
eq(events[1].to,60,"pon_after")
eq(events[1].observation_window_seconds,10,"pon_window_seconds")
eq(events[2].kind,"observation_unavailable","missing_host_event")
eq(events[2].channels,"host","missing_host_only")
eq(events[2].to,nil,"missing_host_not_link_down")

-- A genuine PON recovery can be seen after the failed host observation.
result=feed(item("boot-A",30,51,10000))
eq(result.status,"baseline","rate_baseline_after_partial")
eq(result.events_added,1,"pon_recovered_without_invented_host_event")
eq(result.has_rate,false,"no_rate_through_missing_host")
eq(last_event().kind,"pon_state_change","actual_pon_recovery")
eq(last_event().from,60,"pon_recovery_from_60")
eq(last_event().to,51,"pon_recovery_to_51")

-- Host-link transition remains observable when the PON probe is absent.
result=feed(item("boot-A",40,nil,0))
eq(result.status,"observation_unavailable","missing_pon_classified")
eq(result.events_added,2,"host_transition_and_pon_unknown")
events=recent()
eq(events[#events-1].kind,"host_link_change","independent_host_link_change")
eq(events[#events-1].from,10000,"host_was_10g")
eq(events[#events-1].to,0,"host_observed_down")
eq(events[#events].kind,"observation_unavailable","missing_pon_event")
eq(events[#events].channels,"pon","missing_pon_only")
eq(events[#events].to,nil,"missing_pon_not_a_zero_state")

-- Missing PON means a later 51 is a new baseline, not a fabricated recovery.
result=feed(item("boot-A",50,51,0))
eq(result.status,"baseline","pon_baseline_after_gap")
eq(result.events_added,0,"no_fake_pon_recovery_after_pon_missing")
result=feed(item("boot-A",60,51,10000))
eq(result.status,"valid_interval","normal_interval_restored")
eq(result.events_added,1,"real_host_recovery_observed")
eq(last_event().kind,"host_link_change","real_host_recovery_kind")
eq(last_event().from,0,"host_was_observed_down")
eq(last_event().to,10000,"host_10g_restored")
eq(result.has_rate,true,"valid_counter_rates_restored")

local samples=assert(sampler.recent(state,"samples",16))
eq(samples[4].pon_observation,"unavailable","sample_pon_source_unavailable")
eq(samples[4].host_link_observation,"observed","sample_host_source_observed")
eq(samples[4].pon_state,nil,"missing_pon_not_converted_to_zero")
eq(samples[2].host_link_observation,"unavailable","sample_host_source_unavailable")
eq(samples[2].ethernet_mbps,nil,"missing_link_not_converted_to_down")
eq(samples[6].rate_source,"hardware_ethernet_byte_counters","host_rate_evidence")
verify(samples[6].registration_credential==nil,"no_registration_credential_export")

-- One unavailable event when both channels are missing, no synthetic flaps.
result=feed(item("boot-A",70,nil,nil))
eq(result.events_added,1,"single_both_unavailable_event")
eq(last_event().channels,"pon,host","both_channels_unknown")
result=feed(item("boot-A",80,60,0))
eq(result.status,"baseline","no_rate_through_double_gap")
eq(result.events_added,0,"no_false_transitions_on_restore")
result=feed(item("boot-A",90,51,10000))
eq(result.status,"valid_interval","valid_after_reset")
eq(result.events_added,2,"both_real_transitions_observed")
events=recent()
eq(events[#events-1].kind,"pon_state_change","both_event_pon_order")
eq(events[#events].kind,"host_link_change","both_event_host_order")

-- A long collection gap invalidates both channel baselines.
result=feed(item("boot-A",3701,60,0))
eq(result.status,"sampling_gap","long_gap_marked")
eq(result.events_added,1,"long_gap_does_not_reconstruct_transitions")
eq(last_event().kind,"sampling_gap","gap_event")
result=feed(item("boot-A",3711,51,10000))
eq(result.status,"valid_interval","first_rate_after_gap_baseline_complete")
eq(result.events_added,2,"new_events_after_baseline")
eq(last_event().observation_window_seconds,10,"postgap_event_window_exactly_sampled")

-- Reboot and interface changes reset each independent channel.
result=feed(item("boot-B",1,60,0))
eq(result.status,"reboot","reboot_detected")
eq(result.events_added,1,"reboot_does_not_compare_old_boot_status")
eq(last_event().kind,"reboot_observed","real_reboot_marker")
result=feed(item("boot-B",10,51,10000,"eth1_0"))
eq(result.status,"source_changed","source_change_detected")
eq(result.events_added,1,"source_change_does_not_invent_link_flaps")
eq(last_event().kind,"source_changed","source_changed_marker")
result=feed(item("boot-B",20,nil,1000,"eth1_0"))
eq(result.status,"observation_unavailable","partial_after_source_change")
eq(result.events_added,2,"independent_host_change_after_source_change")
events=recent()
eq(events[#events-1].kind,"host_link_change","host_change_after_source_change")

-- Rejected observations cannot mutate state or generate false history.
local accepted=state.accepted
local before=#recent()
local bad,why=sampler.ingest(state,item("boot-B",20,51,1000,"eth1_0"))
eq(bad,nil,"duplicate_monotonic_time_rejected")
eq(why,"nonmonotonic_observation","duplicate_time_code")
eq(state.accepted,accepted,"rejection_preserves_accepted_count")
eq(#recent(),before,"rejection_preserves_event_ring")
verify(checks>=65,"full_partial_fixture_executed")
print("AOTT_H012_INDEPENDENT_CHANNEL_FIXTURE_PASS checks="..checks)
