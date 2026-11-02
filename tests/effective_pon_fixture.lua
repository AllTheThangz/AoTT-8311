-- AoTT C-011 PON/OMCI noncredential readback fixture, host/MIPS Lua 5.1.
-- Synthetic saved and UCI config. No ONU, network, credential or flash I/O.
local root=assert(arg[1],"require Lua module root")
package.path=root.."/?.lua;"..package.path
local model=require "8311.effective_pon_state"
local probe=require "8311.effective_pon_probe"
local checks=0

local function ok(v,name)
    checks=checks+1
    assert(v,"PON_EFFECTIVE_FIXTURE_FAILED:"..name)
end
local function equal(a,b,name)
    ok(a==b,name)
end

local saved={
    pon_mode="xgspon", omcc_version="0xA3",
    iop_mask="18",mib_file="prx300_1U.ini",
}
local config={
    pon_mode="xgspon",omcc_version="0xA3",
    iop_mask="18",mib_file="/etc/mibs/prx300_1U.ini",
}
local raw="ploam state: current=51 next=51\n"
local read={}
local keys={
    pon_mode={"gpon","ponip","pon_mode"},
    omcc_version={"omci","default","omcc_version"},
    iop_mask={"gpon","ponip","iop_mask"},
    mib_file={"omci","default","mib_file"}
}
local adapter={
    environment=function(id)
        read[#read+1]="env:"..id
        return saved[id] and saved[id].."\n" or nil
    end,
    configured=function(package,section,key)
        read[#read+1]="uci:"..package.."."..section.."."..key
        for id,mapping in pairs(keys) do
            if package==mapping[1] and section==mapping[2] and
               key==mapping[3] then
                return config[id]
            end
        end
        return nil
    end,
    pon_status=function()
        read[#read+1]="native:pon_state"
        return raw
    end
}
local first,err=probe.capture(adapter)
ok(first~=nil,"valid_capture")
equal(err,nil,"no_error")
equal(first.schema,1,"schema")
equal(first.group,"pon_omci_noncredential","scope")
equal(first.no_device_write,true,"not_writer")
equal(first.no_reboot,true,"no_reboot")
equal(first.no_firmware_commits,true,"no_commit")
equal(first.contains_registration_secret,false,"no_published_credentials")
equal(first.source_only_not_hardware_qualified,true,"not_hardware_certified")
equal(first.registration.state,51,"native_pon_state_51")
equal(first.registration.label,"O5.1 associated","native_pon_label")
equal(first.registration.association_observed,true,"native_pon_association")
equal(first.registration.independent_source,"native_pon_psg","native_data_source")
equal(first.registration.proves_internet_connectivity,false,"no_false_WAN")
equal(first.registration.proves_setting_effect,false,"no_false_OMCI_effect")
equal(first.summary.configured,4,"four_uci_fields")
equal(first.summary.saved_match_configured,4,"four_saved_matches")
equal(first.summary.saved_mismatch_configured,0,"no_drift")
equal(first.summary.independently_effective_verified,0,"no_setting_effect_claim")
for _,name in ipairs(model.fields) do
    local row=assert(first.fields[name])
    equal(row.id,name,"field_id_"..name)
    equal(row.configured_source,"uci_vendor_configuration","uci_source_"..name)
    equal(row.saved_to_configured,"match","saved_uci_equal_"..name)
    equal(row.observed_value,nil,"no_runtime_inference_"..name)
    equal(row.observed_source,"unavailable","no_OMCI_readback_"..name)
    equal(row.runtime_effect_proven,false,"no_OMCI_effect_"..name)
    equal(row.persists_across_reboot_proven,false,"no_persistence_"..name)
    equal(row.recovery_proven,false,"no_recovery_"..name)
    equal(row.hardware_qualified,false,"no_auto_qualification_"..name)
end
equal(first.fields.mib_file.configured_value,
      "/etc/mibs/prx300_1U.ini","normalized_mib_path")
equal(#read,9,"only_four_env_four_uci_one_pon")
for _,name in ipairs(read) do
    ok(not name:find("gpon_sn") and
       not name:find("reg_id") and not name:find("loid") and
       not name:find("lpwd") and not name:find("root_pwhash") and
       not name:find("vendor_id"),"no_sensitive_probes")
end

-- The native O5.1 state can be independently observed without proving
-- that any one saved UCI option is being consumed by the running PON stack.
config.iop_mask="20"
local altered=assert(probe.capture(adapter))
equal(altered.fields.iop_mask.saved_to_configured,"mismatch","mismatch_exposed")
equal(altered.fields.iop_mask.runtime_effect_proven,false,
      "changing_uci_does_not_prove_effect")
equal(altered.registration.state,51,"pon_still_associated")
equal(altered.registration.proves_setting_effect,false,
      "association_does_not_cure_config_mismatch")
config.iop_mask="18"

-- Normalization: vendor may spell the mode differently, but only the
-- two declared valid modes are recognized.
saved.pon_mode="XGS-PON"
local normalized=assert(probe.capture(adapter))
equal(normalized.fields.pon_mode.saved_to_configured,"match","mode_normalized")
saved.pon_mode="xgspon"
saved.omcc_version="0xa3"
local canonical=assert(probe.capture(adapter))
equal(canonical.fields.omcc_version.saved_to_configured,"match","omcc_hex_case")
saved.omcc_version="0xA3"
saved.iop_mask="018"
local iop=assert(probe.capture(adapter))
equal(iop.fields.iop_mask.saved_to_configured,"match","iop_canonical_numeric")
saved.iop_mask="18"

-- Invalid or unqualified values do not become false compliance.
config.mib_file="../../etc/shadow"
local unsafe=assert(probe.capture(adapter))
equal(unsafe.fields.mib_file.configured_value,nil,"path_traversal_rejected")
equal(unsafe.fields.mib_file.saved_to_configured,"unverified",
      "missing_valid_config_not_match")
config.mib_file="/etc/mibs/prx300_1U.ini"

config.pon_mode="gpon"
local unsupported=assert(probe.capture(adapter))
equal(unsupported.fields.pon_mode.configured_value,nil,"unsupported_mode_rejected")
equal(unsupported.fields.pon_mode.runtime_effect_proven,false,
      "invalid_mode_never_proven")
config.pon_mode="xgspon"

config.omcc_version="0x81"
local low=assert(probe.capture(adapter))
equal(low.fields.omcc_version.configured_value,nil,"invalid_omcc_low")
config.omcc_version="0xA3"
config.omcc_version="0xC0"
local high=assert(probe.capture(adapter))
equal(high.fields.omcc_version.configured_value,nil,"invalid_omcc_high")
config.omcc_version="0xA3"

config.iop_mask="128"
local over=assert(probe.capture(adapter))
equal(over.fields.iop_mask.configured_value,nil,"invalid_iop_high")
config.iop_mask="18"

-- Invalid/ambiguous native PON responses must be unknown, not made up.
local state,reason=model.parse_pon_status("current=51 next=51")
equal(state,51,"state_parser_realistic")
equal(reason,nil,"state_parser_no_error")
state,reason=model.parse_pon_status("current=51 current=60")
equal(state,nil,"multiple_native_states_rejected")
equal(reason,"ambiguous_pon_state","multiple_native_state_reason")
state,reason=model.parse_pon_status("notcurrent=51")
equal(state,nil,"malformed_key_rejected")
state,reason=model.parse_pon_status("current=abc")
equal(state,nil,"not_numeric_rejected")
state,reason=model.parse_pon_status("current=256")
equal(state,nil,"out_of_range_pon_rejected")
state,reason=model.parse_pon_status(string.rep("x",1500))
equal(state,nil,"too_big_native_output_rejected")

raw="ploam current=60 next=51\n"
local lost=assert(probe.capture(adapter))
equal(lost.registration.state,60,"native_pon_loss_state")
equal(lost.registration.association_observed,false,"not_associated")
equal(lost.registration.proves_internet_connectivity,false,
      "los_does_not_infer_WAN")
raw="ploam current=51 next=51\n"

adapter.pon_status=function() error("synthetic timed-out native command") end
local unknown=assert(probe.capture(adapter))
equal(unknown.registration.state,nil,"failed_probe_is_unknown")
equal(unknown.registration.independent_source,"unavailable",
      "failed_probe_source_missing")
equal(unknown.registration.association_observed,nil,
      "failed_probe_not_false")
adapter.pon_status=function() return raw end

local blank,why=probe.capture({})
equal(blank,nil,"invalid_adapter_rejected")
equal(why,"invalid_readonly_pon_adapter","invalid_adapter_reason")
blank,why=model.inspect(nil,{})
equal(blank,nil,"invalid_input_rejected")
equal(why,"invalid_readonly_pon_inputs","invalid_input_reason")
ok(checks>=90,"adequate_positive_negative_cases")
print("AOTT_C011_PON_OMCI_FIXTURE_PASS checks="..checks)
