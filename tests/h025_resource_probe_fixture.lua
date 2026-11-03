-- H-025 sanitized resource preflight: vendor-MIPS Lua source fixture.
-- All PON, Ethernet, kernel and thermal data are INJECTED, never live.
local root=assert(arg[1],"Lua history source root required")
local overlay=assert(arg[2],"Source overlay Lua root required")
package.path=root.."/?.lua;"..overlay.."/?.lua;"..package.path
local model=require "8311.h025_resource_probe"
local passes=0
local function ok(condition,label)
    passes=passes+1
    assert(condition,"H025_PREFLIGHT_FIXTURE_FAILED:"..label)
end
local function eq(a,b,label) ok(a==b,label) end
local SOURCE_BOOT="11111111-2222-4333-8444-555555555555"
local function make()
    local p={
        reads=0,commands=0,cpu_stage=0,boot=SOURCE_BOOT,
        mem_total=524288,mem_available=212992,rss=2048,
        cpu_read_failure=false,mem_read_failure=false,
        temp_missing=false,reported_temp=41500,
        bad_pon=false,bad_eth=false,
        inject_sensitive=true,short_identity=false,
        clock=100,boot_changed=false,
        unexpected_read=false,
    }
    function p.read(path,maximum)
        p.reads=p.reads+1
        if p.unexpected_read then error("simulated_unreadable_procfs") end
        if path=="/proc/stat" then
            eq(maximum,3072,"bounded_cpu_read")
            p.cpu_stage=p.cpu_stage+1
            if p.cpu_read_failure then return nil end
            if p.cpu_stage%2==1 then
                return "cpu 100 0 40 900 50 0 0 0 0 0\ncpu0 10 0 4 90 5 0 0 0 0 0\n"
            end
            return "cpu 125 0 45 965 50 0 0 0 0 0\n"
        elseif path=="/proc/meminfo" then
            eq(maximum,3072,"bounded_mem_read")
            if p.mem_read_failure then return nil end
            return "MemTotal:       "..p.mem_total.." kB\n"..
                "MemFree:        131072 kB\n"..
                "MemAvailable:   "..p.mem_available.." kB\n"..
                "DirectMap4k:    1248 kB\n"
        elseif path=="/proc/self/status" then
            eq(maximum,4096,"bounded_self_status_read")
            return "Name:\tlua\nState:\tR (running)\nVmRSS:\t"..
                tostring(p.rss).." kB\nThreads:\t1\n"
        elseif path=="/proc/loadavg" then
            eq(maximum,120,"bounded_load_read")
            return "1.25 1.31 1.18 1/100 1200\n"
        elseif path=="/sys/class/thermal/thermal_zone0/temp" then
            eq(maximum,48,"bounded_thermal_read")
            if p.temp_missing then return nil end
            return tostring(p.reported_temp).."\n"
        elseif path=="/proc/sys/kernel/random/boot_id" then
            eq(maximum,80,"bounded_boot_read")
            if p.short_identity then return "invalid\n" end
            return p.boot_changed and
                "22222222-3333-4444-8555-666666666666\n" or p.boot.."\n"
        elseif path=="/proc/uptime" then
            eq(maximum,80,"bounded_uptime_read")
            return tostring(p.clock).." 18.50\n"
        elseif path=="/sys/class/net/eth0_0/speed" then
            eq(maximum,32,"bounded_host_link_read")
            return "10000\n"
        end
        error("unknown_read_path")
    end
    function p.run(argv,limit)
        p.commands=p.commands+1
        local command=table.concat(argv," ")
        if command=="/usr/bin/timeout -k 1 3 /usr/bin/pon psg" then
            eq(limit,1024,"bounded_PON_command")
            if p.bad_pon then return 1,"",false end
            return 0,"current=51\n"..
                (p.inject_sensitive and "VendorSerial: SYNTHETIC_SECRETS_MUST_NOT_EXPORT\n" or ""),false
        elseif command=="/usr/bin/timeout -k 1 4 /usr/sbin/ethtool -S eth0_0" then
            eq(limit,16384,"bounded_host_counter_command")
            if p.bad_eth then return 1,"",false end
            return 0,"RxGoodBytes: 125000000\nTxGoodBytes: 250000000\n"..
                (p.inject_sensitive and "registered_MAC: FAKE_PRIVATE_NOT_FOR_EXPORT\n" or ""),false
        end
        error("unrecognized_native_argv")
    end
    return p
end
local good=make()
local rejected,why=model.capture_once(good,"direct_device")
eq(rejected,nil,"no_direct_execution_mode_without_target")
eq(why,"direct_target_not_authorized","real_target_blocked")
eq(good.reads,0,"gate_blocks_all_kernel_reads")
eq(good.commands,0,"gate_blocks_all_native_commands")
local report=assert(model.capture_once(good,"offline_synthetic"))
eq(report.schema,1,"first_party_schema")
eq(report.source,"h025_injected_readonly_provider","source_label")
eq(report.provenance,"offline_synthetic_unattested","provenance_unattested")
eq(report.hardware_qualified,false,"not_qualified")
eq(report.approved_for_service_start,false,"not_allowed_to_start_daemon")
eq(report.direct_management_authorization_verified,false,"no_target")
eq(report.device_modified,false,"no_writes")
eq(report.firmware_bank_modified,false,"no_bank_change")
eq(report.network_reachability_proven,false,"no_internet_claim")
eq(report.subscriber_wan_throughput_proven,false,"no_bandwidth_claim")
eq(report.pon_observation,"observed","PON_report_observed")
eq(report.host_link_observation,"observed","host_link_observed")
eq(report.host_counters_observation,"observed","host_counter_observed")
eq(report.actual_pon_state,51,"synthetic_O5_1")
eq(report.observed_host_link_mbps,10000,"host_link_speed_not_WAN")
eq(report.mem_total_kib,524288,"sample_memtotal")
eq(report.mem_available_kib,212992,"sample_memavailable")
eq(report.current_process_rss_kib,2048,"bounded_VM_RSS")
eq(report.load_average_1min,1.25,"load_average_not_busy_percent")
eq(report.thermal_zone0_millidegc,41500,"synthetic_thermal")
eq(report.cpu_sample_status,"observed","CPU_delta_valid")
eq(report.memory_sample_status,"observed","memory_delta_valid")
eq(report.process_memory_status,"observed","process_RSS_valid")
eq(report.temperature_sample_status,"observed","thermal_valid")
ok(report.cpu_busy_fraction>0 and report.cpu_busy_fraction<0.5,
   "CPU_window_measured_not_invented")
eq(report.raw_eth_counters_exported,false,"no_raw_counts")
eq(report.boot_epoch_identity_exported,false,"no_boot_uuid")
eq(report.raw_shell_output_exported,false,"no_raw_logs")
eq(report.measured_on_production_board,false,"not_physical_board")
eq(good.commands,2,"exact_two_native_readonly_commands")
eq(good.reads,11,"fixed_kernel_resource_reads")

-- Missing resource data is unavailable, not zero or a green status.
local no_cpu=make()
no_cpu.cpu_read_failure=true
local missing=assert(model.capture_once(no_cpu,"offline_synthetic"))
eq(missing.cpu_busy_fraction,nil,"missing_CPU_not_zero")
eq(missing.cpu_sample_status,"unavailable","CPU_status_unavailable")
eq(missing.mem_total_kib,524288,"other_memory_still_observed")
local no_mem=make()
no_mem.mem_read_failure=true
missing=assert(model.capture_once(no_mem,"offline_synthetic"))
eq(missing.mem_total_kib,nil,"missing_memory_not_fabricated")
eq(missing.mem_available_kib,nil,"missing_headroom_unknown")
eq(missing.memory_sample_status,"unavailable","memory_unavailable")
local no_thermal=make()
no_thermal.temp_missing=true
missing=assert(model.capture_once(no_thermal,"offline_synthetic"))
eq(missing.thermal_zone0_millidegc,nil,"missing_sensor_not_zero")
eq(missing.temperature_sample_status,"unavailable","temperature_unknown")
local bad_memory=make()
bad_memory.mem_available=bad_memory.mem_total+1
missing=assert(model.capture_once(bad_memory,"offline_synthetic"))
eq(missing.mem_total_kib,nil,"memory_available_exceeds_total")
eq(missing.memory_sample_status,"unavailable","reject_invalid_meminfo")
local bad_thermal=make()
bad_thermal.reported_temp=999999
missing=assert(model.capture_once(bad_thermal,"offline_synthetic"))
eq(missing.thermal_zone0_millidegc,nil,"reject_out_of_range_thermal")
local partial=make()
partial.bad_pon=true
missing=assert(model.capture_once(partial,"offline_synthetic"))
eq(missing.pon_observation,"unavailable","failed_PON_not_down")
eq(missing.host_counters_observation,"observed","host_still_observed")
eq(missing.actual_pon_state,nil,"no_inferred_PON_state")
local no_eth=make()
no_eth.bad_eth=true
missing=assert(model.capture_once(no_eth,"offline_synthetic"))
eq(missing.host_counters_observation,"unavailable","counter_failure_not_zero")
eq(missing.observed_host_link_mbps,10000,"host_speed_observation_independent")
local broken_identity=make()
broken_identity.short_identity=true
rejected,why=model.capture_once(broken_identity,"offline_synthetic")
eq(rejected,nil,"missing_boot_identity_fails")
eq(why,"boot_identity_unavailable","boot_error_code")
eq(broken_identity.commands,0,"identity_failure_no_native_commands")
local unknown_reader=make()
unknown_reader.unexpected_read=true
rejected,why=model.capture_once(unknown_reader,"offline_synthetic")
eq(rejected,nil,"no_native_on_untrusted_kernel_reader")
eq(why,"boot_identity_unavailable","kernel_identity_error")

-- No serial, private source output or boot identity is copied to results.
for key,value in pairs(report) do
    eq(type(key),"string","report_key_type")
    if type(value)=="string" then
        ok(not value:find("SYNTHETIC_SECRETS",1,true),
           "serial_string_redacted")
        ok(not value:find("FAKE_PRIVATE",1,true),
           "MAC_string_redacted")
        ok(not value:find(SOURCE_BOOT,1,true),
           "boot_UUID_not_exported")
    end
end

-- Strictly limited JSON fixture for the downstream Python evaluator.
local function json(value)
    local t=type(value)
    if t=="boolean" then return value and "true" or "false" end
    if t=="number" then
        assert(value==value and value~=math.huge and value~=-math.huge)
        return string.format("%.12g",value)
    end
    assert(t=="string")
    return '"'..value:gsub('[%z\1-\31\\\"<>&]',function(c)
        if c=="\\" then return "\\\\" end
        if c=='"' then return '\\"' end
        return string.format("\\u%04x",c:byte())
    end)..'"'
end
local function payload(row)
    local result={}
    for k,v in pairs(row) do
        result[#result+1]=json(k)..":"..json(v)
    end
    table.sort(result)
    return "{"..table.concat(result,",").."}"
end
ok(passes>=75,"full_fixture")
print("AOTT_H025_RESOURCE_SOURCE_FIXTURE_PASS checks="..passes)
if arg[3]=="emit_json" then
    print("AOTT_H025_SANITIZED_SAMPLE="..payload(report))
end
