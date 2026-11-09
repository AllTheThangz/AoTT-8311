-- Synthetic C-011 system and SFP evidence contract, Lua 5.1 / vendor MIPS.
-- All hardware and identity data are invented; no device I/O.
local root=assert(arg[1],"Require overlay Lua module root")
package.path=root.."/?.lua;"..package.path
local model=require "8311.effective_device_state"
local probe=require "8311.effective_device_probe"
local tests=0
local function verify(value,label)
    tests=tests+1
    assert(value,"EFFECTIVE_DEVICE_FIXTURE_FAILED:"..label)
end
local function same(a,b,label)
    verify(a==b,label)
end

local saved={
    hostname="house-onu",lang="en",timezone="UTC",
    ntp_servers="ntp1.example ntp2.example",
    sfp_vendor="TestVendor",sfp_oui="AA:BB:CC",
    sfp_partno="MODEL-TEST",sfp_rev="R1",
    sfp_serial="TEST000001",sfp_date="260101",
    sfp_vendordata="TESTONLY",
}
local config={
    hostname="house-onu",lang="en",timezone="UTC",
    ntp_servers={"ntp1.example","ntp2.example"},
    sfp_eeprom={
        vendor_name="TestVendor",vendor_oui="AA:BB:CC",
        vendor_partno="MODEL-TEST",vendor_rev="R1",
        serial_no="TEST000001",datecode="260101",vendor_data="TESTONLY",
    },
}
local running="house-onu\n"
local reads={}
local adapter={
    environment=function(id)
        reads[#reads+1]="env:"..id
        return saved[id] and saved[id].."\n" or nil
    end,
    system_config=function(key)
        reads[#reads+1]="system:"..key
        return config[key]
    end,
    luci_language=function()
        reads[#reads+1]="luci:lang"
        return config.lang
    end,
    ntp_list=function()
        reads[#reads+1]="ntp:list"
        return config.ntp_servers
    end,
    sfp_option=function(option)
        reads[#reads+1]="sfp:"..option
        return config.sfp_eeprom[option]
    end,
    kernel_hostname=function()
        reads[#reads+1]="kernel:hostname"
        return running
    end,
    active_language=function()
        reads[#reads+1]="runtime:lang"
        return config.lang
    end,
    active_timezone=function()
        reads[#reads+1]="runtime:timezone"
        return config.timezone
    end,
    active_ntp=function()
        reads[#reads+1]="runtime:ntp"
        local peers={}
        for i,value in ipairs(config.ntp_servers or {}) do peers[i]=value end
        return {probe_ok=true,running=#peers>0,peers=peers}
    end,
}

local baseline,reason=probe.capture(adapter)
verify(baseline~=nil,"initial_capture")
same(reason,nil,"initial_no_error")
same(baseline.schema,1,"schema")
same(baseline.group,"device_and_host_visible_sfp","group_name")
same(baseline.no_device_write,true,"no_writes")
same(baseline.no_reboot,true,"no_reboot")
same(baseline.no_firmware_commits,true,"no_commit")
same(baseline.source_only_not_hardware_qualified,true,"no_auto_hardware_qual")
same(baseline.summary.observed_runtime,4,"four_lower_risk_runtime_observed")
same(baseline.summary.configured_only,7,"seven_sfp_configured_only")
same(baseline.summary.unverified,0,"no_missing_config")
same(baseline.summary.saved_matches_runtime,4,"four_runtime_matches")

local total=0
for _,id in ipairs(model.fields) do
    total=total+1
    local field=baseline.fields[id]
    verify(field~=nil,"all_fields_present_"..id)
    same(field.id,id,"consistent_id_"..id)
    same(field.saved_to_configured,"match","matching_config_"..id)
    same(field.hardware_qualified,false,"unqualified_"..id)
    same(field.persists_across_reboot_proven,false,"persistence_not_proven_"..id)
    same(field.recovery_proven,false,"recovery_not_proven_"..id)
    local runtime_fields={hostname=true,lang=true,timezone=true,ntp_servers=true}
    if not runtime_fields[id] then
        same(field.observed_value,nil,"no_invented_running_"..id)
        same(field.runtime_effect_proven,false,"no_invented_effect_"..id)
        same(field.observed_source,"unavailable","no_invented_source_"..id)
    end
end
same(total,11,"eleven_fields")
same(baseline.fields.hostname.observed_value,"house-onu","hostname_runtime")
same(baseline.fields.hostname.observed_source,"kernel_proc_hostname",
     "kernel_hostname_source")
same(baseline.fields.hostname.runtime_effect_proven,true,"hostname_effect")
same(baseline.fields.lang.observed_value,"en","language_request_runtime")
same(baseline.fields.lang.observed_source,"active_luci_request_language",
     "language_runtime_source")
same(baseline.fields.lang.runtime_effect_proven,true,"language_effect")
same(baseline.fields.timezone.observed_value,"UTC","timezone_runtime")
same(baseline.fields.timezone.observed_source,"tmp_localtime_zoneinfo_target",
     "timezone_runtime_source")
same(baseline.fields.timezone.runtime_effect_proven,true,"timezone_effect")
same(baseline.fields.ntp_servers.observed_value,
     "ntp1.example ntp2.example","ntp_runtime_peers")
same(baseline.fields.ntp_servers.observed_source,
     "active_ntpd_process_arguments","ntp_runtime_source")
same(baseline.fields.ntp_servers.runtime_effect_proven,true,"ntp_process_effect")
same(baseline.fields.sfp_serial.sensitivity,"potential_device_identity",
     "identity_classification")
same(baseline.fields.sfp_serial.configured_source,
     "uci_virtual_sfp_eeprom","virtual_sfp_is_configuration")
same(baseline.fields.sfp_vendor.observed_value,nil,"no_claim_host_eeprom")
same(#reads,26,"fixed_read_calls_total")
for _,read in ipairs(reads) do
    verify(not read:find("reg_id") and not read:find("gpon_sn") and
           not read:find("root_pwhash") and not read:find("loid") and
           not read:find("lpwd"),"no_registration_credential_read")
end

running="other-onu\n"
local drift=assert(probe.capture(adapter))
same(drift.fields.hostname.configured_to_observed,"mismatch",
     "configured_hostname_drift")
same(drift.fields.hostname.saved_to_observed,"mismatch",
     "saved_hostname_drift")
same(drift.summary.saved_drift_from_runtime,1,"drift_summary")
same(drift.fields.hostname.runtime_effect_proven,true,"drift_not_hidden")
running="house-onu\n"

saved.hostname="new-name"
local saved_drift=assert(probe.capture(adapter))
same(saved_drift.fields.hostname.saved_to_configured,"mismatch",
     "saved_vs_configured_hostname")
same(saved_drift.fields.hostname.configured_to_observed,"match",
     "configured_equals_kernel")
same(saved_drift.fields.hostname.saved_to_observed,"mismatch",
     "saved_vs_kernel_hostname")
saved.hostname="house-onu"

-- NTP config ordering and whitespace semantics. An unordered or malformed
-- server list is never silently accepted or treated as active sync.
config.ntp_servers={"ntp2.example","ntp1.example"}
local reorder=assert(probe.capture(adapter))
same(reorder.fields.ntp_servers.saved_to_configured,"match",
     "ntp_peer_order_is_semantically_equivalent")
same(reorder.fields.ntp_servers.runtime_effect_proven,true,
     "ntp_active_process_peers_are_runtime_evidence")
same(reorder.fields.ntp_servers.saved_to_observed,"match",
     "ntp_runtime_peer_set_matches_saved")
config.ntp_servers={"ntp1.example","ntp2.example"}
local original_active_ntp=adapter.active_ntp
adapter.active_ntp=function()
    reads[#reads+1]="runtime:ntp"
    return {probe_ok=true,running=true,
            peers={"ntp1.example","dhcp.ntp.example","ntp2.example"}}
end
local extra_ntp=assert(probe.capture(adapter))
same(extra_ntp.fields.ntp_servers.saved_to_observed,"match",
     "configured_ntp_peers_may_coexist_with_dhcp_peer")
same(extra_ntp.fields.ntp_servers.runtime_effect_proven,true,
     "extra_native_ntp_peer_does_not_break_runtime_proof")
adapter.active_ntp=original_active_ntp
config.ntp_servers={"host name with spaces"}
local bad_ntp=assert(probe.capture(adapter))
same(bad_ntp.fields.ntp_servers.configured_value,nil,
     "reject_malformed_ntp_list")
same(bad_ntp.fields.ntp_servers.runtime_effect_proven,false,
     "bad_ntp_not_effect")
config.ntp_servers={"ntp1.example","ntp2.example"}

-- UCI virtual SFP modifications cannot be reported as effective
-- host-router EEPROM, even when saved and UCI match.
config.sfp_eeprom.vendor_name="DifferentVendor"
local altered=assert(probe.capture(adapter))
same(altered.fields.sfp_vendor.saved_to_configured,"mismatch",
     "virtual_sfp_drift_visible")
same(altered.fields.sfp_vendor.runtime_effect_proven,false,
     "virtual_eeprom_runtime_not_proven")
same(altered.fields.sfp_vendor.observed_value,nil,
     "host_eeprom_not_interrogated")
config.sfp_eeprom.vendor_name="TestVendor"

-- Hostname service read error: not valid to fall back to UCI as
-- independent evidence.
local old=adapter.kernel_hostname
adapter.kernel_hostname=function()error("synthetic proc unavailable")end
local nohost=assert(probe.capture(adapter))
same(nohost.fields.hostname.runtime_effect_proven,false,
     "kernel_failure_not_qualified")
same(nohost.fields.hostname.observed_value,nil,"unknown_runtime_hostname")
same(nohost.fields.hostname.configured_value,"house-onu",
     "configured_hostname_still_visible")
adapter.kernel_hostname=old

-- A newline inside a value is forbidden, but one trailing line ending
-- from a fixed CLI or sysfs is accepted.
saved.hostname="bad\nhost"
local bad=assert(probe.capture(adapter))
same(bad.fields.hostname.saved_value,nil,"reject_control_character")
same(bad.fields.hostname.saved_to_configured,"unverified",
     "malformed_saved_unverified")
saved.hostname="house-onu"

-- An adapter returning very large, unsafe or unexpected input does not
-- result in an invented active value or a dangerous shell command.
local orig=adapter.sfp_option
adapter.sfp_option=function()return string.rep("x",3000)end
local invalid=assert(probe.capture(adapter))
same(invalid.fields.sfp_vendor.configured_value,nil,
     "oversized_sfp_config_not_exposed")
same(invalid.fields.sfp_vendor.runtime_effect_proven,false,
     "no_host_verified_on_error")
adapter.sfp_option=orig

local empty,why=probe.capture({})
same(empty,nil,"invalid_adapter_nil")
same(why,"invalid_readonly_device_adapter","invalid_adapter_reason")
local invalidinput,reasoninput=model.inspect(nil,{}, {})
same(invalidinput,nil,"invalid_input_nil")
same(reasoninput,"invalid_readonly_device_inputs","invalid_input_reason")

verify(tests>=115,"adequate_fixture_coverage")
print("AOTT_C011_DEVICE_SFP_FIXTURE_PASS checks="..tests)
