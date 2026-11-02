-- C-011 advanced board/system readbacks, synthetic portable Lua fixture.
-- Never opens a device, reads login material, writes GPIO, changes boot,
-- adjusts Ethernet, or performs any PON registration operation.
local root=assert(arg[1],"overlay Lua module root required")
package.path=root.."/?.lua;"..package.path
local model=require "8311.effective_hardware_state"
local probe=require "8311.effective_hardware_probe"
local count=0
local function ok(v,label)
    count=count+1
    assert(v,"AOTT_HARDWARE_READBACK_FIXTURE_FAILED:"..label)
end
local function eq(a,b,label)
    ok(a==b,label)
end

local saved={
    bootdelay="3",uart_select="on",console_en="1",
    dying_gasp_en="1",rx_los="0",
    ethtool_speed="speed 10000 duplex full autoneg off",
    failsafe_delay="15",persist_root="0",
}
local optic="0"
local gp={
    ["508"]={value="0\n",direction="out\n"},
    ["510"]={value="1\n",direction="out\n"},
    ["505"]={value="0\n",direction="out\n"},
}
local eth="10000\n"
local daemon=true
local accesses={}
local adapter={
    environment=function(id,is_base)
        accesses[#accesses+1]=("env:"..id..":"..tostring(is_base))
        return saved[id] and saved[id].."\n" or nil
    end,
    optic_dg_dis=function()
        accesses[#accesses+1]="uci:optic.common.dg_dis"
        return optic.."\n"
    end,
    gpio=function(pin)
        accesses[#accesses+1]="gpio:"..pin
        return gp[pin]
    end,
    link_speed=function()
        accesses[#accesses+1]="kernel:speed"
        return eth
    end,
    rx_los_daemon=function()
        accesses[#accesses+1]="proc:rx_los"
        return daemon
    end,
}

local report,why=probe.capture(adapter)
ok(report~=nil,"report_present")
eq(why,nil,"valid")
eq(report.schema,1,"schema")
eq(report.group,"advanced_system_and_host","group")
eq(report.source,"read_only_noncredential_hardware_settings","source")
eq(report.no_device_write,true,"read_only")
eq(report.no_reboot,true,"no_reboot")
eq(report.no_firmware_commit,true,"no_commit")
eq(report.contains_credential_material,false,"no_credential")
eq(report.source_only_not_hardware_qualified,true,"not_hardware_qualified")
eq(report.summary.source_fields,8,"eight_fields")
eq(report.summary.fully_effective_verified,0,"no_full_proofs")
eq(report.summary.hardware_qualified,0,"zero_qualified")
eq(report.diagnostics.ethernet.negotiated_speed_mbps,"10000","kernel_speed")
eq(report.diagnostics.ethernet.independent_source,"kernel_sysfs_speed","link_source")
eq(report.diagnostics.ethernet.proves_speed_override_applied,false,
   "link_not_override_proof")
eq(report.diagnostics.ethernet.proves_subscriber_internet,false,"link_not_WAN")
eq(report.diagnostics.gpio.tx_fault_shared_uart_output,"1","uart_shared_gpio")
eq(report.diagnostics.gpio.rx_shared_dying_gasp_output,"0","rx_shared_gpio")
eq(report.diagnostics.gpio.rx_los_output,"0","los_gpio")
eq(report.diagnostics.gpio.gpio_levels_prove_serial_or_optic_signalling,false,
   "gpio_not_signal_proof")
eq(report.diagnostics.rx_los_daemon_present,true,"rx_los_proc")
eq(report.diagnostics.rx_los_daemon_proves_alarm,false,"pid_not_alarm")
eq(report.diagnostics.bootdelay_observed_during_running_session,false,
   "bootdelay_not_live")
eq(report.diagnostics.early_uart_observed_after_boot,false,
   "early_uart_not_live")
eq(report.diagnostics.failsafe_startup_timing_verified,false,
   "failsafe_not_observed")
eq(report.diagnostics.persistent_root_recovery_verified,false,
   "persist_root_not_qualified")

local total=0
for _,id in ipairs(model.fields) do
    local item=assert(report.fields[id])
    total=total+1
    eq(item.id,id,"field_id_"..id)
    eq(item.saved_value,saved[id],"saved_"..id)
    eq(item.runtime_effect_proven,false,"not_proof_"..id)
    eq(item.hardware_qualified,false,"not_qualified_"..id)
    eq(item.reboot_persistence_proven,false,"no_reboot_proof_"..id)
    eq(item.recovery_proven,false,"no_recovery_"..id)
    eq(item.sensitivity,"noncredential","no_secret_"..id)
    eq(item.source_only_not_hardware_qualified,true,"source_only_"..id)
end
eq(total,8,"eight_exact_fields")
eq(report.fields.bootdelay.key_scope,"base_boot_environment","raw_bootdelay")
eq(report.fields.uart_select.key_scope,"base_boot_environment","raw_uart")
eq(report.fields.console_en.key_scope,"aott_prefixed_environment","prefixed_console")
eq(report.fields.dying_gasp_en.configured_value,"1","dg_UCI_inverse")
eq(report.fields.dying_gasp_en.configured_source,
   "uci_optic_common_dg_dis_inverse","dg_UCI_source")
eq(report.fields.dying_gasp_en.saved_to_configured,"match","dg_value_match")
eq(report.fields.dying_gasp_en.observed_effective_value,"1",
   "gpio_508_inferred_state")
eq(report.fields.dying_gasp_en.runtime_effect_proven,false,
   "gpio_not_real_dying_gasp")
eq(report.fields.console_en.observed_effective_value,"1",
   "console_gpio_510")
eq(report.fields.console_en.saved_to_observed,"match",
   "console_pin_matches_saved")
eq(report.fields.console_en.runtime_effect_proven,false,
   "gpio_does_not_prove_console")
eq(report.fields.rx_los.observed_effective_value,nil,
   "pin_level_not_equivalent_to_toggle")
eq(report.fields.ethtool_speed.observed_effective_value,nil,
   "speed_not_same_as_override")
eq(report.fields.ethtool_speed.saved_to_observed,"unverified",
   "speed_override_unverified")
eq(report.fields.persist_root.observed_effective_value,nil,
   "persist_root_not_inferred")
eq(#accesses,14,"only_fixed_reader_calls")
for _,entry in ipairs(accesses) do
    ok(not entry:find("reg_id",1,true) and
       not entry:find("gpon_sn",1,true) and
       not entry:find("loid",1,true) and
       not entry:find("lpwd",1,true) and
       not entry:find("pwhash",1,true) and
       not entry:find("bootcmd",1,true),
       "no_registration_or_credential_reader")
end
ok((table.concat(accesses,","):find("env:bootdelay:true",1,true))~=nil,
   "base_fwenv_bootdelay")
ok((table.concat(accesses,","):find("env:uart_select:true",1,true))~=nil,
   "base_fwenv_uart")
ok((table.concat(accesses,","):find("env:console_en:false",1,true))~=nil,
   "prefixed_fwenv_console")

-- The UCI option can differ from saved without altering kernel
-- data or proving the actual alarm was generated.
optic="1"
local dgdrift=assert(probe.capture(adapter))
eq(dgdrift.fields.dying_gasp_en.configured_value,"0","dg_config_zero")
eq(dgdrift.fields.dying_gasp_en.saved_to_configured,"mismatch",
   "dg_config_drift")
eq(dgdrift.fields.dying_gasp_en.runtime_effect_proven,false,
   "dg_drift_not_optical_alarm")
optic="0"

-- GPIO direction must be an output and value must be canonical.
gp["510"]={value="1\n",direction="in\n"}
local input=assert(probe.capture(adapter))
eq(input.diagnostics.gpio.tx_fault_shared_uart_output,nil,
   "input_gpio_not_output_proof")
eq(input.fields.console_en.observed_effective_value,nil,
   "input_gpio_not_claimed")
gp["510"]={value="invalid",direction="out\n"}
local malformed=assert(probe.capture(adapter))
eq(malformed.diagnostics.gpio.tx_fault_shared_uart_output,nil,
   "malformed_gpio_rejected")
gp["510"]={value="0\n",direction="out\n"}
local drifty=assert(probe.capture(adapter))
eq(drifty.fields.console_en.saved_to_observed,"mismatch",
   "pin_drift_not_hidden")
eq(drifty.fields.console_en.runtime_effect_proven,false,
   "pin_drift_not_console_proof")
gp["510"]={value="1\n",direction="out\n"}

gp["508"]={value="1\n",direction="out\n"}
local dying=assert(probe.capture(adapter))
eq(dying.fields.dying_gasp_en.observed_effective_value,"0",
   "dying_gpio_inverse")
eq(dying.fields.dying_gasp_en.saved_to_observed,"mismatch",
   "dying_pin_drift")
gp["508"]={value="0\n",direction="out\n"}

-- A negotiated speed is observable but never implies a specific
-- speed override was accepted. No forced ethtool operation occurs.
eth="2500\n"
local slower=assert(probe.capture(adapter))
eq(slower.diagnostics.ethernet.negotiated_speed_mbps,"2500",
   "link_speed_observed")
eq(slower.diagnostics.ethernet.proves_speed_override_applied,false,
   "link_not_override")
eth="unsupported\n"
local nospeed=assert(probe.capture(adapter))
eq(nospeed.diagnostics.ethernet.negotiated_speed_mbps,nil,
   "invalid_speed_unknown")
eth="10000\n"

-- Reject dangerous or unexpected saved option strings, without
-- interpreting them or passing them to any setter.
for _,unsafe in ipairs({
    "speed 10000; reboot",
    "speed 10000\nfoo",
    "autoneg off | sh",
    " speed 10000",
    "speed 10000  duplex full",
}) do
    saved.ethtool_speed=unsafe
    local tested=assert(probe.capture(adapter))
    eq(tested.fields.ethtool_speed.saved_value,nil,
       "invalid_ethtool_option_rejected")
    eq(tested.fields.ethtool_speed.runtime_effect_proven,false,
       "bad_ethtool_never_effect")
end
saved.ethtool_speed="speed 10000 duplex full autoneg off"

for _,bad in ipairs({"-1","301","001","NaN"}) do
    saved.failsafe_delay=bad
    local sample=assert(probe.capture(adapter))
    eq(sample.fields.failsafe_delay.saved_value,nil,
       "invalid_failsafe_delay")
end
saved.failsafe_delay="15"
for _,bad in ipairs({"4","01","-1","on"}) do
    saved.bootdelay=bad
    local sample=assert(probe.capture(adapter))
    eq(sample.fields.bootdelay.saved_value,nil,
       "invalid_bootdelay")
end
saved.bootdelay="3"

saved.persist_root="1"
local enabled=assert(probe.capture(adapter))
eq(enabled.fields.persist_root.saved_value,"1","persist_saved")
eq(enabled.fields.persist_root.runtime_effect_proven,false,
   "persist_saved_not_root_recovery")
eq(enabled.fields.persist_root.recovery_proven,false,
   "persist_restore_unqualified")
saved.persist_root="0"

local old=adapter.gpio
adapter.gpio=function()error("synthetic sysfs read failure")end
local failed=assert(probe.capture(adapter))
eq(failed.diagnostics.gpio.tx_fault_shared_uart_output,nil,
   "sysfs_error_unavailable")
eq(failed.fields.dying_gasp_en.runtime_effect_proven,false,
   "sysfs_error_not_effect")
adapter.gpio=old
local oldspeed=adapter.link_speed
adapter.link_speed=function()error("synthetic sysfs failure")end
local failedspeed=assert(probe.capture(adapter))
eq(failedspeed.diagnostics.ethernet.negotiated_speed_mbps,nil,
   "speed_sysfs_error_unavailable")
adapter.link_speed=oldspeed

local empty,reason=probe.capture({})
eq(empty,nil,"missing_adapter")
eq(reason,"invalid_readonly_hardware_adapter","missing_adapter_reason")
local wrong,why=model.inspect(nil,{},{})
eq(wrong,nil,"bad_model_input")
eq(why,"invalid_hardware_readback_input","bad_model_input_reason")

ok(count>=125,"sufficient_regression_cases")
print("AOTT_C011_HARDWARE_FIXTURE_PASS checks="..count)
