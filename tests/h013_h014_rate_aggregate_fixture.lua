-- H-013/H-014: bounded host Ethernet rate aggregation, synthetic only.
-- No actual ONU, network client, device filesystem or source identity export.
local root=assert(arg[1],"Prototype source root required")
package.path=root.."/?.lua;"..package.path
local sampler=require "8311.history_sampler"
local aggregate=require "8311.history_aggregate"
local checks=0
local function ok(value,label)
    checks=checks+1
    assert(value,"H013_AGG_FIXTURE_FAILED:"..label)
end
local function eq(a,b,label) ok(a==b,label) end
local function near(a,b,label)
    ok(type(a)=="number" and math.abs(a-b)<0.000001,label)
end
local function obs(boot,t,pon,speed,rx,tx,source)
    return {
        boot=boot,uptime=t,pon_state=pon,ethernet_mbps=speed,
        source=source or "eth0_0",
        eth={RxGoodBytes=rx,TxGoodBytes=tx},
        subscriber_credential="SYNTHETIC_SHOULD_NOT_ESCAPE",
    }
end
local s=assert(sampler.new({max_samples=16,max_events=16}))
local function add(...)
    local result,reason=sampler.ingest(s,obs(...))
    ok(result~=nil,reason or "ingest_failure")
    return result
end
local function query(seconds)
    local result,reason=sampler.summary(s,seconds)
    ok(result~=nil,reason or "aggregate_failure")
    eq(result.schema,1,"summary_schema")
    eq(result.time_basis,"onu_monotonic_uptime","monotonic_only")
    eq(result.customer_wan_throughput_proven,false,"no_subscriber_speed_claim")
    eq(result.full_internet_availability_proven,false,"no_internet_up_claim")
    eq(result.cross_reboot_continuity_proven,false,"no_reboot_history_claim")
    eq(result.hardware_resource_qualified,false,"offline_not_hardware")
    eq(result.window_complete,false,"no_claim_complete_window")
    eq(result.no_device_write,true,"read_only")
    ok(result.boot==nil and result.eth==nil and
       result.subscriber_credential==nil,"no_private_values_exported")
    return result
end

local empty=query(3600)
eq(empty.status,"no_retained_samples","empty_explicit")
eq(empty.rx.average_mbps,nil,"empty_no_rx_average")
eq(empty.tx.peak_mbps,nil,"empty_no_tx_peak")
eq(empty.samples_considered,0,"empty_zero_samples")
eq(empty.rx.coverage_fraction,0,"empty_zero_coverage")

add("boot-A",10,51,10000,"0","0")
local r=query(3600)
eq(r.samples_considered,1,"one_baseline_sample")
eq(r.status,"no_valid_rate_intervals","one_no_rates")
eq(r.rx.average_mbps,nil,"baseline_is_not_zero_rate")
eq(r.pon_state,51,"latest_pon_source")
eq(r.host_link_speed_mbps,10000,"latest_eth_speed")
eq(r.source,"eth0_0","source_whitelisted")

add("boot-A",20,51,10000,"12500000","5000000")
add("boot-A",30,51,10000,"37500000","12500000")

r=query(25)
eq(r.latest_uptime,30,"window_end_uptime")
eq(r.oldest_relevant_uptime,5,"window_cutoff")
eq(r.samples_considered,3,"three_samples_in_25_seconds")
eq(r.earliest_sample_uptime,10,"first_retained_in_window")
eq(r.observed_span_seconds,20,"sample_span_not_full_window")
eq(r.status,"partial_measured_rates","measured_rate_label")
eq(r.rx.interval_count,2,"two_rx_intervals")
eq(r.tx.interval_count,2,"two_tx_intervals")
near(r.rx.average_mbps,15,"duration_weighted_rx_average")
near(r.tx.average_mbps,5,"duration_weighted_tx_average")
near(r.rx.peak_mbps,20,"rx_peak_20")
near(r.tx.peak_mbps,6,"tx_peak_6")
eq(r.rx.covered_seconds,20,"rx_covered_time")
eq(r.tx.covered_seconds,20,"tx_covered_time")
near(r.rx.coverage_fraction,0.8,"rx_fraction_25sec")
near(r.tx.coverage_fraction,0.8,"tx_fraction_25sec")
eq(r.samples_without_valid_rate,1,"initial_baseline_unmeasured")
eq(r.excluded_cross_window_intervals,0,"no_excluded_intervals_25")

r=query(15)
eq(r.samples_considered,2,"only_two_samples_in_15")
eq(r.excluded_cross_window_intervals,1,"no_partial_rate_interval_inference")
eq(r.samples_without_valid_rate,1,"cross_boundary_unmeasured")
near(r.rx.average_mbps,20,"no_fabricated_boundary_average")
near(r.tx.average_mbps,6,"no_fabricated_boundary_tx")
near(r.rx.coverage_fraction,10/15,"window_15_coverage")

r=query(5)
eq(r.samples_considered,1,"only_latest_sample_5")
eq(r.excluded_cross_window_intervals,1,"last_interval_straddles_window")
eq(r.rx.average_mbps,nil,"no_rate_imputation_last_5")
eq(r.tx.peak_mbps,nil,"no_imputed_peak_last_5")
eq(r.status,"no_valid_rate_intervals","empty_rate_window_status")
eq(r.samples_without_valid_rate,1,"excluded_interval_counted_as_unknown")

r=query(90*86400)
eq(r.requested_window_seconds,7776000,"90_day_query_allowed")
eq(r.window_complete,false,"90days_not_claimed_as_available")
eq(r.history_exhausted,true,"retained_history_end_seen")
eq(r.samples_considered,3,"only_three_samples_for_90days")
near(r.rx.coverage_fraction,20/7776000,"90day_observed_fraction")
eq(r.full_internet_availability_proven,false,"90days_is_not_WAN_history")

-- One direction can be measured without imputing the other.
add("boot-A",40,51,10000,"50000000",nil)
r=query(40)
eq(r.rx.interval_count,3,"third_rx_interval")
eq(r.tx.interval_count,2,"no_fake_tx_interval")
near(r.rx.average_mbps,(10+20+10)/3,"rx_weighted_30s")
near(r.tx.average_mbps,5,"tx_only_measured_20s")
eq(r.tx.covered_seconds,20,"tx_time_excludes_missing")
eq(r.rx.covered_seconds,30,"rx_time_includes_valid_direction")
eq(r.tx.peak_mbps,6,"tx_peak_from_eligible_intervals")

-- Missing optical state must not silently fill in traffic rate history.
add("boot-A",50,nil,10000,"62500000",nil)
r=query(50)
eq(r.unavailable_pon_samples,1,"pon_outage_not_assumed")
eq(r.samples_without_valid_rate,2,"baseline_and_missing")
eq(r.rx.covered_seconds,30,"no_cross_missing_rate")
eq(r.tx.covered_seconds,20,"no_fake_missing_tx_rate")
eq(r.pon_observation,"unavailable","current_pon_unknown")
eq(r.host_link_observation,"observed","host_still_observed")
add("boot-A",60,51,10000,"75000000","15000000")
add("boot-A",70,51,10000,"87500000","20000000")
r=query(70)
eq(r.samples_considered,7,"seven_samples_in_current_boot")
eq(r.unavailable_pon_samples,1,"missing_sample_retained")
eq(r.rx.interval_count,4,"four_noncontiguous_valid_rx_intervals")
eq(r.tx.interval_count,3,"three_valid_tx_intervals")
eq(r.rx.covered_seconds,40,"rx_interval_coverage_not_full_span")
eq(r.tx.covered_seconds,30,"tx_interval_coverage_not_full_span")
near(r.rx.average_mbps,12.5,"rx_avg_across_separated_valid_intervals")
near(r.tx.average_mbps,(4+6+4)/3,"tx_avg_only_valid_intervals")
eq(r.latest_uptime,70,"latest_monotonic_epoch")
eq(r.observed_span_seconds,60,"span_distinct_from_coverage")

-- Crossing a long blind interval never implies a 1-hour average.
local result=add("boot-A",5000,51,10000,"100000000","25000000")
eq(result.status,"sampling_gap","gap_status")
r=query(24*3600)
eq(r.samples_considered,1,"gap_stops_previous_segments")
eq(r.terminated_at_epoch_boundary,true,"epoch_boundary_explicit")
eq(r.rx.average_mbps,nil,"gap_has_no_measured_rates")
eq(r.rx.covered_seconds,0,"no_gap_time_imputation")
add("boot-A",5010,51,10000,"112500000","30000000")
r=query(24*3600)
eq(r.samples_considered,2,"current_gap_epoch_only")
eq(r.rx.interval_count,1,"first_postgap_rate")
near(r.rx.average_mbps,10,"postgap_actual_rx")
near(r.tx.average_mbps,4,"postgap_actual_tx")
eq(r.terminated_at_epoch_boundary,true,"gap_boundary_retained")
eq(r.samples_without_valid_rate,1,"gap_baseline_unknown")

-- Reboot observed: new boot uptime must not be merged into old rate window.
result=add("boot-B",2,51,10000,"0","0")
eq(result.status,"reboot","reboot_marker")
r=query(7*86400)
eq(r.samples_considered,1,"only_new_boot_counted")
eq(r.terminated_at_epoch_boundary,true,"boot_epoch_barrier")
eq(r.rx.average_mbps,nil,"no_cross_reboot_average")
add("boot-B",12,51,10000,"1250000","2500000")
r=query(7*86400)
near(r.rx.average_mbps,1,"new_boot_rx_average")
near(r.tx.average_mbps,2,"new_boot_tx_average")
eq(r.rx.covered_seconds,10,"only_new_boot_coverage")

-- Source switch never compares different host Ethernet interfaces.
result=add("boot-B",22,51,10000,"0","0","eth1_0")
eq(result.status,"source_changed","source_switch_status")
r=query(3600)
eq(r.source,"eth1_0","whitelisted_source_changed")
eq(r.samples_considered,1,"source_change_is_boundary")
eq(r.rx.interval_count,0,"no_cross_source_traffic")
add("boot-B",32,51,10000,"2500000","5000000","eth1_0")
r=query(3600)
near(r.rx.average_mbps,2,"new_source_rx")
near(r.tx.average_mbps,4,"new_source_tx")
eq(r.terminated_at_epoch_boundary,true,"source_change_barrier")

-- More samples than the ordinary 100-item export cap still aggregate
-- from a bounded ring, never by requesting unbounded raw history.
local large=assert(sampler.new({max_samples=120,max_events=128}))
for i=1,350 do
    local s0=obs("boot-C",i,51,10000,
        tostring(i*125000),tostring(i*250000))
    local value,reason=sampler.ingest(large,s0)
    ok(value~=nil,"350_sample_ingest_"..tostring(i)..":"..tostring(reason))
end
local big=assert(sampler.summary(large,3600))
eq(big.samples_considered,120,"full_fixed_120_sample_ring")
eq(big.rx.interval_count,120,"aggregate_beyond_100_raw_export_limit")
near(big.rx.average_mbps,1,"evicted_old_samples_rx_avg")
near(big.tx.average_mbps,2,"evicted_old_samples_tx_avg")
eq(big.rx.covered_seconds,120,"120_second_valid_coverage")
eq(big.history_exhausted,true,"bounded_ring_has_oldest_retained")
eq(big.window_complete,false,"ring_retention_not_full_1h")
local rows=assert(sampler.recent(large,"samples",100))
eq(#rows,100,"raw_export_still_capped_100")
ok(big.boot==nil and big.eth==nil,"aggregate_redacts_counters_and_boot")

-- No invalid query mutates retained history or counter baselines.
local accepted=large.accepted
for _,window in ipairs({0,-1,7776001,math.huge,0/0,1.5,"3600"}) do
    local invalid,reason=sampler.summary(large,window)
    eq(invalid,nil,"reject_invalid_window_"..tostring(window))
    eq(reason,"invalid_rate_window","invalid_window_code")
    eq(large.accepted,accepted,"failed_query_no_ingest")
end
local invalid=sampler.summary(large,{window_seconds=3600})
eq(invalid,nil,"reject_unrecognized_table_window")
invalid=sampler.summary(nil,3600)
eq(invalid,nil,"reject_nil_history")
local corrupt=assert(sampler.new({max_samples=4,max_events=4}))
corrupt.samples_count=5
invalid=sampler.summary(corrupt,60)
eq(invalid,nil,"reject_invalid_ring_count")
corrupt.samples_count=1
corrupt.samples[1]={at_uptime=42,source="credential",status="baseline"}
invalid=sampler.summary(corrupt,60)
eq(invalid,nil,"reject_identity_like_source")
corrupt.samples[1]={at_uptime=42,source="eth0_0",status="invalid"}
invalid=sampler.summary(corrupt,60)
eq(invalid,nil,"reject_unknown_status")
corrupt.samples[1]={at_uptime=42,source="eth0_0",status="valid_interval",
    elapsed_seconds=10,rx_mbps=100,rate_source="fake"}
invalid=sampler.summary(corrupt,60)
eq(invalid,nil,"reject_untrusted_rate_source")

-- Future 1h/24h/7d/30d/90d views consume only bounded summaries.
local windows=assert(sampler.history_windows(large))
eq(windows.schema,1,"five_window_schema")
for _,row in ipairs({
    {"hour",3600},{"day",86400},{"week",604800},
    {"month",2592000},{"ninety_days",7776000},
}) do
    local panel=windows[row[1]]
    ok(panel~=nil,"five_window_panel_present_"..row[1])
    eq(panel.requested_window_seconds,row[2],"five_window_duration_"..row[1])
    eq(panel.window_complete,false,"five_window_no_fake_history_"..row[1])
    eq(panel.customer_wan_throughput_proven,false,"no_WAN_speed_"..row[1])
    eq(panel.samples_considered,120,"bounded_120_"..row[1])
end

-- A corrupted ring can never turn unvalidated status or source into
-- an exported hostname, device token or false optical measurement.
corrupt.samples[1]={at_uptime=42,source="eth0_0",status="baseline",
    pon_state="SERIAL_SHAPED_GARBAGE"}
invalid=sampler.summary(corrupt,60)
eq(invalid,nil,"invalid_pon_state_cannot_leak")
corrupt.samples[1]={at_uptime=42,source="eth0_0",status="baseline",
    ethernet_mbps="INVALID_LINK_STATUS"}
invalid=sampler.summary(corrupt,60)
eq(invalid,nil,"invalid_host_speed_cannot_leak")
corrupt.samples[1]={at_uptime=42,source="eth0_0",status="baseline",
    pon_observation="connected_to_all_internet"}
invalid=sampler.summary(corrupt,60)
eq(invalid,nil,"invalid_observation_provenance")

ok(checks>=450,"full_aggregation_fixture_executed")
print("AOTT_H013_H014_AGGREGATION_FIXTURE_PASS checks="..tostring(checks))
