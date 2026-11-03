-- H-017: independent router WAN probe evidence, synthetic Lua 5.1/MIPS.
-- NO actual router targets, network probes, timers or device modification.
local root=assert(arg[1],"Source prototype root required")
package.path=root.."/?.lua;"..package.path
local model=require "8311.wan_evidence"
local checks=0
local function ok(x,label)
    checks=checks+1
    assert(x,"H017_EVIDENCE_FIXTURE_FAILED:"..label)
end
local function eq(actual,expected,label)
    ok(actual==expected,label)
end
local function probe(slot,kind,result,latency)
    return {slot=slot,kind=kind,result=result,latency_ms=latency,
        target_label="SYNTHETIC_UNEXPORTED_TARGET"}
end
local function obs(boot,uptime,probes)
    return {
        origin="router_wan", clock_domain="router_monotonic",
        boot=boot,uptime=uptime,probes=probes,
        destination="SYNTHETIC_NONROUTABLE_TARGET",
        raw_output="SYNTHETIC_SHOULD_NOT_EXPORT",
        device_identifier="SYNTHETIC_SHOULD_NOT_EXPORT",
    }
end
local state=assert(model.new({max_events=8,max_samples=8}))
local bad,reason=model.new({max_samples=100000})
eq(bad,nil,"reject_unbounded_sample_cap")
eq(reason,"invalid_capacity","invalid_sample_cap_reason")
bad=model.new({max_events=1})
eq(bad,nil,"reject_single_event_cap")
bad=model.new("wrong")
eq(bad,nil,"reject_options_type")
local first=obs("router-boot-A",10,{
    probe(1,"https","pass",25),probe(2,"dns","fail"),
})
local receipt=assert(model.ingest(state,first))
eq(receipt.schema,1,"receipt_schema")
eq(receipt.status,"one_or_more_targets_reached","one_reachable_target")
eq(receipt.passed,1,"one_pass")
eq(receipt.failed,1,"one_fail")
eq(receipt.latency_ms_min,25,"single_success_min_latency")
eq(receipt.latency_ms_max,25,"single_success_max_latency")
eq(receipt.events_added,0,"first_is_baseline")
eq(receipt.source,"declared_router_wan_probes","declared_provenance")
eq(receipt.declared_source_is_not_authenticated,true,"not_trusted_router_identity")
eq(receipt.no_isp_failure_cause_proven,true,"no_isp_fault_claim")
eq(receipt.not_global_internet_reachability_proof,true,"one_target_not_internet_proof")
eq(receipt.no_network_or_device_action,true,"no_commands")

local combined=model.combine(51,10000,receipt)
eq(combined.pon_association,"o5_1_associated","pon_registered")
eq(combined.host_link_speed,"host_speed_nonzero","host_speed_present")
eq(combined.router_probe_evidence,"one_or_more_targets_reached","independent_router_evidence")
eq(combined.router_source_authenticated,false,"router_auth_not_claimed")
eq(combined.simultaneous_measurement_unverified,true,"independent_timestamps")
eq(combined.proves_isp_fault,false,"no_isp_cause")
eq(combined.proves_full_internet_reachability,false,"no_global_wan_claim")
eq(combined.customer_wan_bandwidth_unmeasured,true,"no_subscriber_speed_claim")
combined=model.combine(51,0,receipt)
eq(combined.host_link_speed,"host_speed_zero","zero_host_speed_observed")
eq(combined.router_probe_evidence,"one_or_more_targets_reached","WAN_not_derived_from_host")
combined=model.combine(51,10000,nil)
eq(combined.router_probe_evidence,"unavailable","PON_not_substitute_for_WAN")
combined=model.combine(nil,nil,{status="one_or_more_targets_reached"})
eq(combined.router_probe_evidence,"unavailable","untrusted_receipt_rejected")
combined=model.combine(60,nil,receipt)
eq(combined.pon_association,"not_o5_1_associated","PON_state_separate")
eq(combined.host_link_speed,"unknown","missing_host_unknown")
combined=model.combine(51,0,receipt)
eq(combined.pon_association,"o5_1_associated","PON_not_from_WAN")

-- All configured targets fail, not proof of ISP outage.
receipt=assert(model.ingest(state,obs("router-boot-A",20,{
    probe(1,"https","fail"),probe(2,"dns","fail"),
})))
eq(receipt.status,"all_submitted_probes_failed","target_failure_not_isp_cause")
eq(receipt.events_added,1,"transition_registered")
local events=assert(model.recent(state,"events",8))
eq(#events,1,"single_change_event")
eq(events[1].kind,"router_probe_result_change","actual_probe_result_changed")
eq(events[1].from,"one_or_more_targets_reached","prior_reachability")
eq(events[1].to,"all_submitted_probes_failed","observed_failures")
eq(events[1].observation_window_seconds,10,"transition_time_window")
eq(events[1].isp_failure_cause_unverified,true,"no_inferred_provider_cause")
eq(events[1].walltime_trust,"unknown","do_not_invent_calendar_time")
ok(events[1].boot==nil and events[1].target_label==nil,"no_identity_or_target_export")
local samples=assert(model.recent(state,"samples",8))
eq(#samples,2,"sample_history")
eq(samples[2].failed,2,"two_target_failures")
eq(samples[2].latency_ms_min,nil,"failed_probe_has_no_fabricated_latency")
eq(samples[1].latency_ms_min,25,"successful_latency_retained_without_target")
ok(samples[2].destination==nil and samples[2].raw_output==nil,
   "no_target_or_raw_response_leak")

-- Partial probe failure produces inconclusive evidence, not an outage.
receipt=assert(model.ingest(state,obs("router-boot-A",30,{
    probe(1,"https","fail"),probe(2,"dns","unknown"),
})))
eq(receipt.status,"inconclusive","unknown_result_not_isp_loss")
eq(receipt.events_added,1,"classification_change")
eq(model.recent(state,"events",8)[2].kind,"router_probe_evidence_change",
   "unknown_transition_not_wan_recovery")
receipt=assert(model.ingest(state,obs("router-boot-A",40,{
    probe(1,"https","fail"),probe(2,"dns","unknown"),
})))
eq(receipt.events_added,0,"repeated_unknown_does_not_fill_history")
receipt=assert(model.ingest(state,obs("router-boot-A",50,{})))
eq(receipt.status,"unavailable","no_configured_probes")
eq(receipt.events_added,1,"unavailable_once")
receipt=assert(model.ingest(state,obs("router-boot-A",60,{})))
eq(receipt.events_added,0,"repeated_absence_not_event_storm")
receipt=assert(model.ingest(state,obs("router-boot-A",70,{
    probe(1,"https","pass",31),
})))
eq(receipt.status,"one_or_more_targets_reached","new_evidence_from_unknown")
eq(receipt.events_added,1,"evidence_available_not_claimed_recovery")
eq(model.recent(state,"events",8)[4].kind,"router_probe_evidence_change",
   "from_unknown_not_real_recovery")

-- Mixed router boot epochs and long gaps cannot interpolate outage times.
receipt=assert(model.ingest(state,obs("router-boot-B",1,{
    probe(1,"https","fail"),
})))
eq(receipt.events_added,1,"reboot_only")
eq(model.recent(state,"events",8)[5].kind,"router_reboot_observed",
   "reboot_not_wan_outage")
receipt=assert(model.ingest(state,obs("router-boot-B",3705,{
    probe(1,"https","pass",100),
})))
eq(receipt.events_added,1,"long_gap_only")
eq(model.recent(state,"events",8)[6].kind,"router_probe_sampling_gap",
   "sampling_gap_not_recovery")
local e=assert(model.recent(state,"events",8))
eq(e[6].observation_window_seconds,3704,"gap_bounds_not_exact_outage")

-- Reject malformed/duplicate/stale router evidence without storing it.
local accepted=state.accepted
local before_samples=state.samples_count
local before_events=state.events_count
local function reject(record,label)
    local result=model.ingest(state,record)
    eq(result,nil,label)
    eq(state.accepted,accepted,label.."_no_mutation")
    eq(state.samples_count,before_samples,label.."_samples_untouched")
    eq(state.events_count,before_events,label.."_events_untouched")
end
reject(obs("router-boot-B",3705,{probe(1,"https","pass",3)}),
       "same_time_rejected")
reject(obs("router-boot-B",3704,{probe(1,"https","pass",3)}),
       "backward_time_rejected")
reject(obs("router-boot-B",3706,{probe(1,"foo","pass")}),
       "unrecognized_probe_type")
reject(obs("router-boot-B",3706,{probe(1,"https","success")}),
       "unrecognized_result")
reject(obs("router-boot-B",3706,{probe(1,"https","fail",12)}),
       "failed_probe_cannot_have_success_latency")
reject(obs("router-boot-B",3706,{probe(1,"https","pass",-1)}),
       "negative_latency")
reject(obs("router-boot-B",3706,{
    probe(1,"https","pass"),probe(1,"dns","fail")}),
    "duplicate_target_slot")
reject(obs("router-boot-B",3706,{probe(5,"https","pass")}),
       "slot_above_max")
reject(obs("router-boot-B",3706,{
    probe(1,"https","pass"),probe(2,"dns","pass"),
    probe(3,"icmp","pass"),probe(4,"tcp","pass"),
    probe(1,"https","pass")}),"five_probes_rejected")
local bad_clock=obs("router-boot-B",3706,{probe(1,"https","pass")})
bad_clock.clock_domain="onu_monotonic"
reject(bad_clock,"cross_clock_source_rejected")
local wrong_origin=obs("router-boot-B",3706,{probe(1,"https","pass")})
wrong_origin.origin="onu"
reject(wrong_origin,"ONU_not_router_WAN_evidence")
local bad_boot=obs("",3706,{probe(1,"https","pass")})
reject(bad_boot,"missing_boot_id")
local bad_uptime=obs("router-boot-B",0/0,{probe(1,"https","pass")})
reject(bad_uptime,"nan_router_uptime")
local wrong_indices=obs("router-boot-B",3706,{})
wrong_indices.probes[9]=probe(1,"https","pass")
reject(wrong_indices,"sparse_probe_array")

local invalid,why=model.recent(state,"samples",101)
eq(invalid,nil,"export_cap_enforced")
eq(why,"invalid_query_limit","export_cap_reason")
invalid,why=model.recent(state,"secrets",10)
eq(invalid,nil,"unknown_collection_rejected")
samples=assert(model.recent(state,"samples",8))
local original=samples[#samples].status
samples[#samples].status="externally_mutated"
eq(model.recent(state,"samples",8)[#samples].status,
   original,"export_not_mutable_internal_state")

-- RAM-only bounded event/sample history under repeatedly changing reports.
local long=assert(model.new({max_samples=2,max_events=2}))
for i=1,1000 do
    local result=assert(model.ingest(long,obs("router-boot-C",i,{
        probe(1,"https",i%2==0 and "pass" or "fail",i%2==0 and 3 or nil),
    })))
    ok(result.no_isp_failure_cause_proven,"1000_bounded_event_"..i)
end
eq(long.samples_count,2,"sample_ring_bounded_1000")
eq(long.events_count,2,"event_ring_bounded_1000")
samples=assert(model.recent(long,"samples",2))
eq(samples[1].at_router_uptime,999,"old_sample_evicted")
eq(samples[2].at_router_uptime,1000,"latest_sample_retained")
events=assert(model.recent(long,"events",2))
eq(#events,2,"only_two_latest_events")
ok(checks>=1000,"all_synthetic_checks_completed")
print("AOTT_H017_WAN_EVIDENCE_FIXTURE_PASS checks="..tostring(checks))
