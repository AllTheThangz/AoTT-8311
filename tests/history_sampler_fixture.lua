-- H-011: deterministic, synthetic in-memory sampling tests.
-- No clock reads, actual device access, network calls or filesystem writes.
local root=assert(arg[1],"Overlay Lua source directory required")
package.path=root.."/?.lua;"..root.."/?/init.lua;"..package.path
local sampler=require "8311.history_sampler"
local checks=0
local function ok(test,label)
    checks=checks+1
    assert(test,"H011_FIXTURE_FAILED:"..label)
end
local function eq(a,b,label) ok(a==b,label) end
local function sample(boot,uptime,pon,link,rx,tx,source)
    return {
        boot=boot,uptime=uptime,pon_state=pon,ethernet_mbps=link,
        source=source or "eth0_0",
        eth={RxGoodBytes=rx,TxGoodBytes=tx},
        -- These synthetic extras must never be copied into a report.
        gpon_sn="SENSITIVE_SYNTHETIC_ID",
        loid="SENSITIVE_SYNTHETIC_LOID",
        password="SENSITIVE_SYNTHETIC_PASSWORD",
    }
end
local state,err=sampler.new({max_samples=3,max_events=2})
ok(state~=nil,"valid_capacity")
eq(state.schema,1,"schema")
local invalid= sampler.new({max_samples=999999})
eq(invalid,nil,"bounded_samples_config")
invalid= sampler.new({max_events=1})
eq(invalid,nil,"two_simultaneous_events_required")
invalid= sampler.new("invalid")
eq(invalid,nil,"invalid_config_type")

local initial=sample("boot-A",10,51,10000,"1000","500")
local got,why=sampler.ingest(state,initial)
ok(got~=nil,"initial_accepted")
eq(got.status,"baseline","initial_status")
eq(got.has_rate,false,"initial_is_not_a_rate")
eq(got.events_added,0,"initial_does_not_fake_connection_event")

local records=assert(sampler.recent(state,"samples",3))
eq(#records,1,"initial_record_count")
eq(records[1].rate_unavailable,"no_comparable_interval","no_first_rate")
eq(records[1].walltime_trust,"unknown","no_assumed_clock_accuracy")
ok(records[1].boot==nil,"boot_private")
ok(records[1].gpon_sn==nil,"pon_serial_not_copied")
ok(records[1].loid==nil,"loid_not_copied")
ok(records[1].password==nil,"credential_not_copied")
ok(records[1].eth==nil,"raw_counters_not_exported")

local second=sample("boot-A",20,51,10000,"10001000","5000500")
got=assert(sampler.ingest(state,second))
eq(got.status,"valid_interval","normal_interval")
eq(got.events_added,0,"normal_no_events")
eq(got.has_rate,true,"rates_available")
records=assert(sampler.recent(state,"samples",3))
ok(math.abs(records[2].rx_mbps-8.0)<0.000001,"rx_rate_8_mbps")
ok(math.abs(records[2].tx_mbps-4.0)<0.000001,"tx_rate_4_mbps")
eq(records[2].rate_source,"hardware_ethernet_byte_counters","sample_origin")
eq(records[2].direction,"host_interface_rx_tx","host_not_isp_speed")

local third=sample("boot-A",30,51,10000,"12001000",nil)
got=assert(sampler.ingest(state,third))
eq(got.has_rate,true,"single_good_counter_rate")
records=assert(sampler.recent(state,"samples",3))
eq(records[3].tx_mbps,nil,"unknown_tx_not_zero")
eq(records[3].tx_unavailable,"invalid_counter","unknown_tx_reason")
local observed=sample("boot-A",40,60,1000,"14001000","900500")
got=assert(sampler.ingest(state,observed))
eq(got.events_added,2,"two_independent_transitions")
eq(got.status,"valid_interval","status_still_normal_interval")
records=assert(sampler.recent(state,"samples",3))
eq(#records,3,"sample_ring_fixed_capacity")
eq(records[1].at_uptime,20,"oldest_sample_evicted")
local events=assert(sampler.recent(state,"events",2))
eq(#events,2,"event_ring_cap")
eq(events[1].kind,"pon_state_change","pon_transition")
eq(events[1].observation_window_seconds,10,"change_window_not_exact")
eq(events[2].kind,"host_link_change","link_transition")

-- Invalid/nonmonotonic samples do not mutate retained records.
got,why=sampler.ingest(state,sample("boot-A",40,51,10000,"16001000","1000500"))
eq(got,nil,"equal_time_rejected")
eq(why,"nonmonotonic_observation","equal_time_reason")
eq(state.accepted,4,"rejected_sample_no_state_change")
got,why=sampler.ingest(state,sample("boot-A",39,51,10000,"16001000","1000500"))
eq(got,nil,"reverse_time_rejected")
eq(state.accepted,4,"reverse_time_no_state_change")

-- A failed PON probe must not be inferred as PON down.
got=assert(sampler.ingest(state,sample("boot-A",50,nil,10000,nil,nil)))
eq(got.status,"observation_unavailable","missing_pon_not_a_link_loss")
eq(got.has_rate,false,"missing_pon_no_throughput")
events=assert(sampler.recent(state,"events",2))
eq(events[2].kind,"observation_unavailable","missing_pon_observable")
got=assert(sampler.ingest(state,sample("boot-A",60,51,10000,"17001000","1000500")))
eq(got.status,"baseline","restored_probes_reset_baseline")
eq(got.events_added,0,"no_false_recovered_pon_event")

-- New interface source: reset rates rather than subtract unrelated counters.
got=assert(sampler.ingest(state,sample("boot-A",70,51,10000,"0","0","eth1_0")))
eq(got.status,"source_changed","source_changed_status")
eq(got.has_rate,false,"different_interface_not_subtracted")
events=assert(sampler.recent(state,"events",2))
eq(events[2].kind,"source_changed","source_change_event")

-- Same PON/host values after reboot: reboot event, no fake continuity.
got=assert(sampler.ingest(state,sample("boot-B",1,51,10000,"200","200","eth1_0")))
eq(got.status,"reboot","reboot_discontinuity")
eq(got.has_rate,false,"reboot_no_counter_delta")
events=assert(sampler.recent(state,"events",2))
eq(events[2].kind,"reboot_observed","reboot_event")
ok(events[2].boot==nil,"reboot_boot_id_not_exported")

-- Large sample gap: must mark the gap without inventing its transitions.
got=assert(sampler.ingest(state,sample("boot-B",3702,60,0,"1000","500","eth1_0")))
eq(got.status,"sampling_gap","long_gap_detected")
eq(got.has_rate,false,"long_gap_no_rates")
events=assert(sampler.recent(state,"events",2))
eq(events[2].kind,"sampling_gap","long_gap_event")
eq(events[2].observation_window_seconds,3701,"gap_window")

-- Sanitize arbitrary input, bound query sizes and protect retained copies.
got,why=sampler.ingest(state,sample("boot-B",3703,60,0,"99999999999999999999999999","999999999999999999999","eth1_0"))
ok(got~=nil,"malformed_counters_dont_kill_status_history")
eq(got.has_rate,false,"bad_counters_not_zero_filled")
records=assert(sampler.recent(state,"samples",3))
eq(records[#records].rate_unavailable,"no_valid_counter_pairs","bad_counter_reason")
local prior=records[#records].status
records[#records].status="client-mutated"
local retry=assert(sampler.recent(state,"samples",3))
eq(retry[#retry].status,prior,"export_copies_not_mutable_internals")
invalid,why=sampler.recent(state,"samples",101)
eq(invalid,nil,"export_limit_enforced")
eq(why,"invalid_query_limit","export_limit_reason")
invalid,why=sampler.recent(state,"invalid",5)
eq(invalid,nil,"unknown_collection_rejected")
got,why=sampler.ingest(state,sample("bad space",3704,60,0,"1200","1000"))
eq(got,nil,"invalid_boot_name")
got,why=sampler.ingest(state,sample("boot-B",3704,60,0,"1200","1000","../leak"))
eq(got,nil,"pathlike_source_rejected")
got,why=sampler.ingest(state,sample("boot-B",0/0,60,0,"1200","1000"))
eq(got,nil,"nan_time_rejected")
got,why=sampler.ingest(state,sample("boot-B",3704,60,0,"1200","1000","ABCD12345678"))
eq(got,nil,"serial_shaped_source_rejected")
got,why=sampler.ingest(state,sample("boot-B",3704,60,0,"1200","1000","secret"))
eq(got,nil,"arbitrary_source_rejected")
eq(state.accepted,10,"invalid_input_does_not_commit")

-- Ring bounds and retained Lua heap are bounded under 1,000 samples.
local small=assert(sampler.new({max_samples=2,max_events=2}))
collectgarbage("collect")
local heap_before=collectgarbage("count")
for i=1,1000 do
    local ans=sampler.ingest(small,sample("boot-C",i,51,10000,tostring(1000+i),tostring(100+i)))
    ok(ans~=nil,"1000_sample_ingest_"..i)
end
eq(small.samples_count,2,"fixed_sample_limit_1000")
eq(small.accepted,1000,"all_1000_accepted")
records=assert(sampler.recent(small,"samples",2))
eq(records[1].at_uptime,999,"oldest_999")
eq(records[2].at_uptime,1000,"newest_1000")
eq(small.events_count,0,"no_spurious_events_over_1000")
collectgarbage("collect")
local heap_delta_kib=collectgarbage("count")-heap_before
ok(heap_delta_kib < 64,"bounded_retained_heap_under_64_kib_for_1000_samples")

ok(checks>=1050,"full_fixture_executed")
print("AOTT_H011_RAM_SAMPLER_FIXTURE_PASS checks="..tostring(checks))
