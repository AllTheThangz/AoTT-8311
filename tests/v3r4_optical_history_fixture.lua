-- V3r4 optical/thermal history integration, memory-only PRX126 sensor fixture.
local overlay=assert(arg[1],"overlay Lua root")
package.path=overlay.."/?.lua;"..package.path
local optical=require "8311.history_optical_probe"
local native=require "8311.history_native_probe"
local sampler=require "8311.history_sampler"
local exporter=require "8311.history_export"
local shape=require "8311.history_snapshot_shape"
local assertions=0
local function eq(a,b,name)
    assertions=assertions+1
    assert(a==b,"OPTICAL:"..name.." got="..tostring(a)..
           " expected="..tostring(b))
end
local A="11111111-2222-4333-8444-555555555555"
local B="22222222-3333-4444-8555-666666666666"
-- Only DDM bytes offset 96-105 encode optical measurements; all earlier
-- raw EEPROM bytes may contain unrelated private provisioning information.
local bytes=string.rep("S",96)..string.char(
    42,148,124,209,71,216,164,40,1,185
)
eq(#bytes,106,"bounded_ddm_block")
local measurement=assert(optical.decode_eeprom(bytes))
eq(measurement.optic_temp_c,42+148/256,"signed_ddm_temp")
eq(measurement.module_voltage_v,3.1953,"voltage_scaled")
eq(measurement.tx_bias_ma,36.784,"laser_bias_scaled")
eq(math.abs(measurement.rx_power_dbm-10*math.log10(.0441))<.0001,true,"rx_dbm_scaled")
eq(math.abs(measurement.tx_power_dbm-10*math.log10(4.2024))<.0001,true,"tx_dbm_scaled")
eq(measurement.eeprom,nil,"no_raw_eeprom_copy")
eq(measurement.serial,nil,"no_private_serial")
local raw=string.rep("\0",106)
eq(optical.decode_eeprom(raw).rx_power_dbm,nil,"zero_power_missing")
local absent=optical.decode_eeprom(bytes:sub(1,105))
eq(absent,nil,"truncated_eeprom_refused")
local bad_temp=string.rep("X",96)..string.char(
    127,255,124,209,71,216,164,40,1,185
)
eq(optical.decode_eeprom(bad_temp).optic_temp_c,nil,"unrealistic_temp_unavailable")

local count={reads={},runs={}}
local current=A
local uptime=100
local function provider(options)
    options=options or {}
    local p={}
    function p.read(path,max)
        count.reads[#count.reads+1]=path
        if path=="/proc/sys/kernel/random/boot_id" then
            return current.."\n"
        elseif path=="/proc/uptime" then
            return tostring(uptime).." 55.00\n"
        elseif path==optical.paths.eeprom then
            eq(max,106,"eeprom_bound")
            if options.eeprom==false then return nil end
            return bytes
        elseif path==optical.paths.cpu0 then
            eq(max,80,"thermal0_bound")
            return "52279\n"
        elseif path==optical.paths.cpu1 then
            eq(max,80,"thermal1_bound")
            return "51085\n"
        elseif path=="/sys/class/net/eth0_0/speed" then
            return "10000\n"
        end
        error("unexpected_file_path:"..path)
    end
    function p.run(argv,max)
        count.runs[#count.runs+1]=table.concat(argv," ")
        local cmd=table.concat(argv," ")
        if cmd:find("ethtool",1,true) then
            return 0,"RxGoodBytes: 100000\nTxGoodBytes: 200000\n",false
        elseif cmd:find("pon psg",1,true) then
            return 0,"current=51\n",false
        end
        error("unexpected_command:"..cmd)
    end
    return p
end
local p=provider()
local all=assert(optical.read_once(p))
eq(all.cpu0_temp_c,52.279,"cpu0_temp")
eq(all.cpu1_temp_c,51.085,"cpu1_temp")
eq(all.rx_power_dbm~=nil,true,"optical_present")
local optics_only,avail=assert(native.read_selected(
    p,{pon=false,host=false,optical=true}))
eq(optics_only.observed.pon,false,"no_pon_impersonation")
eq(optics_only.observed.host,false,"no_host_impersonation")
eq(optics_only.observed.optical,true,"optical_selected")
eq(avail.optical,"observed","optical_available")
eq(#count.runs,0,"optical_only_spawns_no_commands")
eq(optics_only.optics.cpu0_temp_c,52.279,"optical_cpu_combined")
local state=assert(sampler.new())
local receipt=assert(sampler.ingest_selected(state,optics_only))
eq(receipt.status,"baseline","optical_start_baseline")
local initial=assert(sampler.recent(state,"samples",1))[1]
eq(initial.optical_observation,"observed","optics_in_sample")
eq(initial.pon_observation,"not_sampled","pon_not_sampled")
eq(initial.host_link_observation,"not_sampled","host_not_sampled")
eq(initial.rx_power_dbm~=nil,true,"rx_in_history")
local projected=assert(exporter.project(state,"hour",100,"local_runtime"))
eq(projected.optics_history_unavailable,false,"actual_optics_present")
eq(shape.validate(projected),true,"strict_optical_projection_accepted")
eq(projected.samples[1].cpu1_temp_c,51.085,"cpu_temp_redacted_numeric")
eq(projected.samples[1].boot,nil,"boot_id_not_exported")
eq(projected.samples[1].eeprom,nil,"eeprom_not_exported")
local bad=assert(exporter.project(state,"hour",100,"local_runtime"))
bad.optics_history_unavailable=true
eq(shape.validate(bad),nil,"false_missing_optics_claim_rejected")
bad=assert(exporter.project(state,"hour",100,"local_runtime"))
bad.samples[1].rx_power_dbm=-100
eq(shape.validate(bad),nil,"out_of_range_rx_rejected")
bad=assert(exporter.project(state,"hour",100,"local_runtime"))
bad.samples[1].optical_observation="not_sampled"
eq(shape.validate(bad),nil,"optical_data_must_be_observed")
bad=assert(exporter.project(state,"hour",100,"local_runtime"))
bad.samples[1].private_mac="REDACTED_PRIVATE_LABEL"
eq(shape.validate(bad),nil,"unexpected_fields_rejected")

-- Native optical read failure must not turn a missing RX value into 0dBm.
uptime=160
local missing=assert(native.read_selected(provider({eeprom=false}),{
    pon=false,host=false,optical=true}))
eq(missing.optics.rx_power_dbm,nil,"missing_rx_not_zero")
eq(missing.optics.cpu0_temp_c,52.279,"cpu_survives_mailbox_failure")
assert(sampler.ingest_selected(state,missing))
local latest=assert(sampler.recent(state,"samples",1))[1]
eq(latest.rx_power_dbm,nil,"no_false_rx")
eq(latest.optical_observation,"observed","cpu_observed")
local combined=assert(native.read_selected(provider(),{
    pon=true,host=true,optical=false}))
uptime=220
-- Last native observation uptime 160; clone current sample time to 220
-- to exercise PON and host without forging a simultaneous optical sample.
combined.uptime=220
local combined_receipt=assert(sampler.ingest_selected(state,combined))
eq(combined_receipt.status,"baseline","first_host_baseline")
local noopt=assert(sampler.recent(state,"samples",1))[1]
eq(noopt.optical_observation,"not_sampled","optical_unscheduled")
eq(noopt.rx_power_dbm,nil,"no_stale_optics")

-- Future optic-only observations do not overwrite Ethernet byte-counter
-- baselines; the next real Ethernet sample uses its own real delta span.
uptime=250
local part=assert(native.read_selected(provider(),{
    pon=false,host=false,optical=true}))
assert(sampler.ingest_selected(state,part))
uptime=280
local host=assert(native.read_selected(provider(),{
    pon=false,host=true,optical=false}))
host.eth.RxGoodBytes="200000"
host.eth.TxGoodBytes="400000"
local done=assert(sampler.ingest_selected(state,host))
eq(done.has_rate,true,"optical_only_did_not_reset_host_baseline")

-- A reboot is a new monotonic epoch. Previous optics and host data cannot
-- be represented as continuous with post-reboot sample timestamps.
current=B;uptime=1
local new=assert(native.read_selected(provider(),{
    pon=false,host=false,optical=true}))
local reboot=assert(sampler.ingest_selected(state,new))
eq(reboot.status,"reboot","optical_only_reboot_detected")
local newpublic=assert(exporter.project(state,"hour",100,"local_runtime"))
eq(shape.validate(newpublic),true,"new_epoch_projection_valid")
eq(#newpublic.samples,1,"pre_reboot_sample_not_exposed")
eq(newpublic.actual_isp_uptime_unverified,true,"no_wan_proof")
eq(newpublic.history_is_volatile,true,"no_flash_claim")
eq(assertions>=39,true,"minimum_coverage")
if arg[2]=="emit_json" then
    local demo=assert(sampler.new({max_samples=30,max_events=16}))
    local function optical_sample(time,reading)
        return assert(sampler.ingest_selected(demo,{
            boot=A,uptime=time,source="eth0_0",
            observed={pon=false,host=false,optical=true},
            optics=reading,
        }))
    end
    optical_sample(100,{
        rx_power_dbm=-13.60,tx_power_dbm=6.23,
        optic_temp_c=42.5,cpu0_temp_c=52.0,
        cpu1_temp_c=51.0,tx_bias_ma=36.8,module_voltage_v=3.19,
        password="DO_NOT_LEAK_PRIVATE",
    })
    optical_sample(160,{
        rx_power_dbm=-14.10,tx_power_dbm=6.10,
        optic_temp_c=43.5,cpu0_temp_c=52.5,
        cpu1_temp_c=51.8,tx_bias_ma=36.9,module_voltage_v=3.20,
    })
    optical_sample(220,nil) -- an unavailable mailbox/thermal tick
    optical_sample(280,{
        rx_power_dbm=-13.92,tx_power_dbm=6.13,
        optic_temp_c=42.7,cpu0_temp_c=52.2,
        cpu1_temp_c=51.5,tx_bias_ma=37.1,module_voltage_v=3.18,
    })
    local payload=assert(exporter.export_json(demo,"hour",100,"local_runtime"))
    print("AOTT_V3R4_OPTICAL_JSON="..payload)
end
print("AOTT_V3R4_OPTICAL_RAM_HISTORY_PASS assertions="..assertions)
