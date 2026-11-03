-- Pure Lua 5.1 counter/history model tests. Runs on host and vendor MIPS.
local source = assert(arg[1], "model path required")
local model = assert(loadfile(source))()
local checks = 0
local function ok(expr, label)
    checks = checks + 1
    assert(expr, "HISTORY_FIXTURE_FAILED:" .. label)
end
local function equal(actual, expected, name)
    ok(actual == expected, name)
end

equal(model.counter_delta("0","0"),"0","zero_delta")
equal(model.counter_delta("100","145"),"45","simple_decimal_delta")
equal(model.counter_delta("18446744073709551610","18446744073709551615"),
      "5","exact_uint64_max_delta")
equal(model.counter_delta("9007199254740993","9007199254741093"),
      "100","correct_over_2_to_53")
local bad, why = model.counter_delta("110","90")
equal(bad,nil,"regressed_counter_nil")
equal(why,"counter_reset_or_wrap","regressed_reason")
bad, why = model.counter_delta("0","18446744073709551616")
equal(bad,nil,"out_of_uint64_range")
equal(why,"invalid_counter","out_of_range_reason")
bad = model.counter_delta("1","2e3")
equal(bad,nil,"no_scientific_notation")
bad = model.counter_delta("1","-2")
equal(bad,nil,"no_negative_counter")
bad = model.counter_delta("1","1.5")
equal(bad,nil,"no_fraction")
bad = model.counter_delta(0 / 0,"5")
equal(bad,nil,"no_nan")
bad = model.counter_delta(9007199254740992,"9007199254740993")
equal(bad,nil,"no_inexact_floating_source")

local original = {
    boot="test-boot-A", uptime=100.0,
    eth={RxGoodBytes="9007199254740993",TxGoodBytes="1000"},
}
local after = {
    boot="test-boot-A", uptime=110.0,
    eth={RxGoodBytes="9007200454740993",TxGoodBytes="20001000"},
}
local rate = assert(model.eth_rates(original,after))
ok(math.abs(rate.rx_mbps - 960.0) < 0.0001,"exact_counter_to_mbps")
ok(math.abs(rate.tx_mbps - 16.0) < 0.0001,"tx_counter_mbps")
equal(rate.direction,"host_interface_rx_tx","not_inferred_wan_direction")
equal(rate.elapsed_seconds,10.0,"monotonic_interval")

local missing = {boot="test-boot-A",uptime=111,
    eth={RxGoodBytes="9007200454741013"}}
local value, error_code = model.eth_rates(after,missing)
ok(value ~= nil,"partial_counter_pair_returned")
ok(value.rx_mbps > 0,"partial_rx_rate")
equal(value.tx_mbps,nil,"missing_tx_not_zeroed")
equal(value.tx_mbps_unavailable,"invalid_counter","missing_tx_reason")

local changed_boot={boot="test-boot-B",uptime=1,eth=after.eth}
value,error_code=model.eth_rates(after,changed_boot)
equal(value,nil,"reboot_rates_rejected")
equal(error_code,"reboot_or_unknown_boot","reboot_marker")
value,error_code=model.eth_rates(after,after)
equal(value,nil,"zero_interval_rejected")
equal(error_code,"invalid_sampling_interval","zero_interval_marker")

local first={boot="test-boot-A",uptime=10,pon_state=51,ethernet_mbps=10000}
local next={boot="test-boot-A",uptime=25,pon_state=51,ethernet_mbps=10000}
local list,marker=model.observe_transition(nil,first,{},{})
equal(list,nil,"invalid_limit_rejected")
equal(marker,"invalid_event_limit","limit_error")
list,marker=model.observe_transition(nil,first,{},2)
equal(#list,0,"initial_no_fake_events")
equal(marker,"initial_baseline","initial_marker")

list,marker=model.observe_transition(first,next,list,2)
equal(#list,0,"stable_no_events")
equal(marker,"unchanged","stable_marker")
local lost={boot="test-boot-A",uptime=40,pon_state=60,ethernet_mbps=1000}
list,marker=assert(model.observe_transition(next,lost,list,2))
equal(#list,2,"pon_and_link_events")
equal(marker,"pon,ethernet","combined_transition_marker")
equal(list[1].kind,"pon_state_change","pon_kind")
equal(list[1].from,51,"pon_from")
equal(list[1].to,60,"pon_to")
equal(list[1].observation_window_seconds,15,"window_not_exact_outage")
equal(list[2].kind,"host_link_change","host_kind")
equal(list[2].to,1000,"host_speed_new")
local recovered={boot="test-boot-A",uptime=60,pon_state=51,ethernet_mbps=10000}
list,marker=assert(model.observe_transition(lost,recovered,list,2))
equal(#list,2,"bounded_events_retention")
equal(list[1].kind,"pon_state_change","oldest_evicted")
equal(list[2].kind,"host_link_change","latest_event")
equal(list[1].from,60,"recovery_pon_from")
equal(list[1].to,51,"recovery_pon_to")

local restart={boot="test-boot-B",uptime=4,pon_state=20,ethernet_mbps=10000}
list,marker=assert(model.observe_transition(recovered,restart,list,2))
equal(marker,"reboot","reboot_history_marker")
equal(#list,2,"bounded_reboot_event")
equal(list[2].kind,"reboot_observed","reboot_event_label")
equal(list[2].at_uptime,4,"restart_monotonic_time")
equal(list[2].walltime_trust,"unknown","no_fake_calendar_time")
equal(list[2].boot,nil,"no_boot_identifier_leaked")

local reversed={boot="test-boot-B",uptime=2,pon_state=20,ethernet_mbps=10000}
local invalid,problem=model.observe_transition(restart,reversed,list,2)
equal(invalid,nil,"negative_time_no_history")
equal(problem,"invalid_sampling_interval","negative_time_marker")
ok(checks >= 45,"full_fixture_exercised")
print("AOTT_VNEXT_PORTABLE_HISTORY_MODEL_FIXTURE_PASS checks="..tostring(checks))
