-- H-011 native adapter contract, synthetic inputs and no live ONU access.
-- Run under Lua 5.1 and separately extracted vendor MIPS Lua/QEMU.
local root=assert(arg[1],"Prototype root required")
local overlay=assert(arg[2],"Existing source overlay Lua root required")
package.path=root.."/?.lua;"..overlay.."/?.lua;"..package.path
local probe=require "8311.history_native_probe"
local sampler=require "8311.history_sampler"
local checked=0
local function ok(value,label)
    checked=checked+1
    assert(value,"H011_NATIVE_FIXTURE_FAILED:"..label)
end
local function eq(actual,expected,label) ok(actual==expected,label) end

local A="11111111-2222-4333-8444-555555555555"
local B="22222222-3333-4444-8555-666666666666"
local PON="/usr/bin/timeout -k 1 3 /usr/bin/pon psg"
local ETH="/usr/bin/timeout -k 1 4 /usr/sbin/ethtool -S eth0_0"
local function mk(opts)
    opts=opts or {}
    local p={files={},runs={},opts=opts,boot_reads=0,uptime_reads=0}
    function p.read(path,max)
        p.files[#p.files+1]={path=path,max=max}
        if opts.raise_read and opts.raise_read==path then error("synthetic_file_failure") end
        if path=="/proc/sys/kernel/random/boot_id" then
            eq(max,80,"boot_read_limit")
            p.boot_reads=p.boot_reads+1
            if opts.boot==false then return nil end
            if p.boot_reads==2 and opts.boot_end~=nil then return opts.boot_end end
            return opts.boot or A.."\n"
        elseif path=="/proc/uptime" then
            eq(max,80,"uptime_read_limit")
            p.uptime_reads=p.uptime_reads+1
            if opts.uptime==false then return nil end
            if p.uptime_reads==2 and opts.uptime_end~=nil then return opts.uptime_end end
            return opts.uptime or "100.25 32.31\n"
        elseif path=="/sys/class/net/eth0_0/speed" then
            eq(max,32,"speed_read_limit")
            if opts.speed==false then return nil end
            return opts.speed or "10000\n"
        end
        error("UNEXPECTED_NATIVE_PATH:"..tostring(path))
    end
    function p.run(argv,max)
        local cmd=table.concat(argv," ")
        p.runs[#p.runs+1]={command=cmd,max=max}
        if opts.raise_run and opts.raise_run==cmd then
            error("synthetic_process_exception")
        end
        if cmd==PON then
            eq(max,1024,"pon_output_bound")
            return opts.pon_exit or 0, opts.pon or "current=51\n", opts.pon_overflow or false
        elseif cmd==ETH then
            eq(max,16384,"eth_output_bound")
            return opts.eth_exit or 0, opts.eth or
                "NIC statistics:\n RxGoodBytes: 1000\n TxGoodBytes: 2000\n", opts.eth_overflow or false
        end
        error("UNEXPECTED_NATIVE_COMMAND:"..cmd)
    end
    return p
end

local par=probe.parsers
eq(par.boot(A.."\n"),A,"canonical_uuid")
eq(par.boot(string.upper(A)),A,"case_normalized")
eq(par.boot(string.rep("0",8).."-0000-0000-0000-000000000000"),nil,"no_null_uuid")
eq(par.boot(A.." trailing"),nil,"no_extra_boot_content")
eq(par.boot("bad-boot"),nil,"bad_uuid")
eq(par.boot(A.."\n"..B),nil,"two_boot_ids_rejected")
eq(par.uptime("123.25 90.00\n"),123.25,"monotonic_uptime")
eq(par.uptime("1e3 20"),nil,"no_scientific_uptime")
eq(par.uptime("-1.0 20"),nil,"no_negative_uptime")
eq(par.uptime("NaN 1"),nil,"no_nan_uptime")
eq(par.uptime("123"),nil,"two_fields_required")
eq(par.speed("10000\n"),10000,"host_10g_speed")
eq(par.speed("0\n"),0,"link_down_observation")
eq(par.speed("-1\n"),nil,"negative_driver_code_unavailable")
eq(par.speed("4294967295\n"),nil,"unknown_speed_unavailable")

local pair,reason=par.ethtool("RxGoodBytes: 9007199254740993\nTxGoodBytes: 18446744073709551615\n")
ok(pair~=nil,"uint64_as_strings")
eq(pair.RxGoodBytes,"9007199254740993","rx_u64_exact")
eq(pair.TxGoodBytes,"18446744073709551615","tx_u64_max_exact")
pair,reason=par.ethtool("RxGoodBytes: 1\n RxGoodBytes: 2\n")
eq(pair,nil,"duplicate_counter_refused")
eq(reason,"ambiguous_eth_counter","duplicate_reason")
pair,reason=par.ethtool("RxGoodBytes: 18446744073709551616\n")
eq(pair,nil,"reject_u64_overflow")
eq(reason,"invalid_eth_counter","overflow_reason")
pair,reason=par.ethtool("RxGoodBytes: 5\nTxGoodBytes: -1\n")
ok(pair~=nil and pair.RxGoodBytes=="5" and pair.TxGoodBytes==nil,
   "partial_parse_not_zero_filled")
pair,reason=par.ethtool("RxGoodBytes: 100\nTxGoodBytes: 200\n"..string.rep("X",17000))
eq(pair,nil,"oversize_report_refused")
pair,reason=par.ethtool("No usable counters\n")
eq(pair,nil,"no_counters_refused")

local p=mk()
local v,avail=probe.read_once(p)
ok(v~=nil,"one_shot_snapshot")
eq(v.boot,A,"boot_id_internally_preserved")
eq(v.source,"eth0_0","fixed_interface")
eq(v.uptime,100.25,"source_uptime")
eq(v.pon_state,51,"native_pon_state")
eq(v.ethernet_mbps,10000,"native_link_speed")
eq(v.eth.RxGoodBytes,"1000","source_exact_rx")
eq(v.eth.TxGoodBytes,"2000","source_exact_tx")
eq(avail.proves_subscriber_internet,false,"pon_not_wan")
eq(avail.no_device_write,true,"native_readonly_contract")
eq(#p.runs,2,"two_processes_only")
eq(p.runs[1].command,PON,"fixed_pon_argv")
eq(p.runs[2].command,ETH,"fixed_eth_argv")
eq(#p.files,5,"only_three_fixed_kernel_paths_read_five_times")
for _,x in ipairs(p.files) do
    ok(x.path=="/proc/sys/kernel/random/boot_id" or
       x.path=="/proc/uptime" or
       x.path=="/sys/class/net/eth0_0/speed",
       "whitelisted_path")
end

local state=assert(sampler.new({max_samples=3,max_events=3}))
local receipt=assert(probe.collect_one(state,mk()))
eq(receipt.status,"baseline","initial_sampler_read")
eq(receipt.samples_retained,1,"one_retained")
eq(receipt.has_rate,false,"no_fake_baseline_speed")
eq(receipt.availability.pon,"observed","pon_observed_flag")
ok(receipt.boot==nil,"boot_id_never_in_receipt")
ok(receipt.eth==nil,"raw_counters_not_in_receipt")
ok(receipt.loid==nil,"subscriber_identity_not_in_receipt")
ok(receipt.password==nil,"credential_not_in_receipt")

receipt=assert(probe.collect_one(state,mk({
    uptime="110.25 99.00\n",
    eth="RxGoodBytes: 9001000\nTxGoodBytes: 5002000\n"
})))
eq(receipt.status,"valid_interval","real_rate_interval")
eq(receipt.has_rate,true,"valid_rate_exists")
local recent=assert(sampler.recent(state,"samples",3))
ok(math.abs(recent[2].rx_mbps-7.2)<0.00001,"native_rx_7_2_mbps")
ok(math.abs(recent[2].tx_mbps-4.0)<0.00001,"native_tx_4_mbps")
eq(recent[2].direction,"host_interface_rx_tx","host_direction_label")

receipt=assert(probe.collect_one(state,mk({
    uptime="120.25 9.0\n",pon="current=60\n",speed="0\n",
    eth="RxGoodBytes: 9501000\nTxGoodBytes: 6002000\n"
})))
eq(receipt.events_added,2,"two_realtime_state_transitions")
local events=assert(sampler.recent(state,"events",3))
eq(events[1].kind,"pon_state_change","native_pon_transition")
eq(events[2].kind,"host_link_change","native_host_transition")

receipt=assert(probe.collect_one(state,mk({
    uptime="130.25 9.0\n",pon_exit=124,
    eth="RxGoodBytes: 10001000\nTxGoodBytes: 6502000\n"
})))
eq(receipt.availability.pon,"unavailable","pon_timeout_unknown")
eq(receipt.status,"observation_unavailable","probe_failure_not_fiber_loss")
eq(receipt.has_rate,false,"failed_pon_not_false_rate")
events=assert(sampler.recent(state,"events",3))
eq(events[#events].kind,"observation_unavailable","no_false_down_transition")
local r0,why=probe.collect_one(state,mk({uptime="130.25 9.0\n"}))
eq(r0,nil,"repeated_sample_rejected")
eq(why,"nonmonotonic_observation","monotonic_gate")

receipt=assert(probe.collect_one(state,mk({
    boot=B.."\n",uptime="2.25 1.0\n",
    eth="RxGoodBytes: 50\nTxGoodBytes: 50\n",
})))
eq(receipt.status,"reboot","new_boot_resets_counters")
eq(receipt.has_rate,false,"no_cross_boot_rate")
events=assert(sampler.recent(state,"events",3))
eq(events[#events].kind,"reboot_observed","reboot_observed_from_boot_id")
ok(events[#events].boot==nil,"event_does_not_expose_boot_id")

-- Fail closed without launching a process when monotonic identity is unknown.
local bad=mk({boot=false})
local sample,e=probe.read_once(bad)
eq(sample,nil,"boot_read_failure")
eq(e,"boot_identity_unavailable","boot_error_code")
eq(#bad.runs,0,"no_native_spawn_on_boot_failure")
bad=mk({boot="ALL-ZEROS"})
sample,e=probe.read_once(bad)
eq(sample,nil,"invalid_boot_rejected")
bad=mk({uptime=false})
sample,e=probe.read_once(bad)
eq(sample,nil,"missing_uptime_rejected")
eq(e,"monotonic_time_unavailable","uptime_error")
eq(#bad.runs,0,"no_commands_if_uptime_unknown")

bad=mk({uptime_end=false})
sample,e=probe.read_once(bad)
eq(sample,nil,"missing_final_monotonic_time_rejected")
eq(e,"observation_window_unavailable","missing_final_time_reason")
bad=mk({uptime_end="90.0 1.0\n"})
sample,e=probe.read_once(bad)
eq(sample,nil,"time_regression_during_sampling_rejected")
eq(e,"observation_window_out_of_bounds","time_regression_reason")
bad=mk({uptime_end="120.5 1.0\n"})
sample,e=probe.read_once(bad)
eq(sample,nil,"sampling_duration_over_12_seconds_rejected")
eq(e,"observation_window_out_of_bounds","sampling_duration_reason")
bad=mk({boot_end=B.."\n"})
sample,e=probe.read_once(bad)
eq(sample,nil,"reboot_during_sample_rejected")
eq(e,"boot_changed_during_observation","mixed_boot_epoch_reason")
local elapsed,availability=assert(probe.read_once(mk({uptime_end="101.75 1.0\n"})))
eq(elapsed.uptime,101.75,"end_uptime_is_sample_time")
eq(availability.observation_window_seconds,1.5,"acquisition_duration_recorded")

-- All individual probe failures are independently unavailable, not zero.
v,avail=assert(probe.read_once(mk({
    speed=false,pon="current=51 current=60\n",eth_overflow=true,
})))
eq(v.pon_state,nil,"ambiguous_pon_rejected")
eq(v.ethernet_mbps,nil,"unavailable_link_not_zero")
eq(v.eth.TxGoodBytes,nil,"overflow_eth_not_consumed")
eq(avail.pon,"unavailable","invalid_pon_availability")
eq(avail.host_link,"unavailable","invalid_speed_availability")
eq(avail.host_counters,"unavailable","oversize_eth_availability")
eq(avail.proves_subscriber_internet,false,"no_isp_inference")

v,avail=assert(probe.read_once(mk({
    raise_run=PON,eth_exit=124,
})))
eq(v.pon_state,nil,"pon_command_exception")
eq(v.eth.RxGoodBytes,nil,"eth_timeout")
eq(avail.host_counters,"unavailable","eth_timeout_availability")

local invalid_state_provider=mk()
local nope,nope_reason=probe.collect_one(nil,invalid_state_provider)
eq(nope,nil,"invalid_state_rejected")
eq(nope_reason,"invalid_state","invalid_state_reason")
eq(#invalid_state_provider.files,0,"invalid_state_no_kernel_reads")
eq(#invalid_state_provider.runs,0,"invalid_state_no_spawns")
local malformed=probe.read_once({})
eq(malformed,nil,"provider_requires_both_callbacks")

-- Run the actual native_once entrypoint with the native libraries mocked.
-- These mock dependencies make no filesystem, process or network calls.
local native=mk({uptime="55.5 10.5\n",pon="current=51\n"})
package.preload["nixio.fs"]=function()
    return {readfile=function(path,max) return native.read(path,max) end}
end
package.preload["8311.webutil"]=function()
    return {capture=function(argv,max) return native.run(argv,max) end}
end
local native_state=assert(sampler.new({max_samples=2,max_events=2}))
local native_receipt=assert(probe.native_once(native_state))
eq(native_receipt.status,"baseline","native_once_mocked_path_passes")
eq(native_receipt.no_device_write,true,"native_wrapper_no_device_write")
eq(#native.runs,2,"native_once_two_bounded_processes")
eq(#native.files,5,"native_once_five_bounded_kernel_reads")
for _,run in ipairs(native.runs) do
    ok(run.command==PON or run.command==ETH,"native_only_fixed_timeout_commands")
end
ok(native_receipt.boot==nil,"native_never_returns_boot_id")
ok(checked>150,"complete_native_fixture")
print("AOTT_H011_NATIVE_ONE_SHOT_FIXTURE_PASS checks="..tostring(checked))
