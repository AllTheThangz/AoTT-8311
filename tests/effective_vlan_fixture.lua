-- C-011 synthetic ISP VLAN readback fixture, portable Lua 5.1/MIPS.
-- Never invokes native traffic control, hooks, flash writes or ONU commands.
local root=assert(arg[1],"Lua module directory required")
package.path=root.."/?.lua;"..package.path
local model=require "8311.effective_vlan_state"
local probe=require "8311.effective_vlan_probe"
local tests=0
local function ok(value,name)
    tests=tests+1
    assert(value,"VLAN_EFFECTIVE_FIXTURE_FAILED:"..name)
end
local function same(a,b,name)
    ok(a==b,name)
end
local ONE=string.rep("a",64)
local TWO=string.rep("b",64)
local saved={fix_vlans="1",internet_vlan="200",services_vlan="36"}
local receipt=table.concat({
    "# Unicast VLAN ID from ISP side",
    "UNICAST_VLAN=100",
    "MULTICAST_GEM=",
    "INTERNET_PMAP=pmapper1",
    "INTERNET_GEMS=\"gem12 gem13\"",
    "SERVICES_PMAP=pmapper2",
    "SERVICES_GEMS=",
    "INTERNET_VLAN=200",
    "SERVICES_VLAN=36",
    "DEFAULT_SERVICES_VLAN=100",
    "STATE_HASH="..ONE,
    "",
},"\n")
local current=ONE
local running=true
local requests={}
local adapter={
    environment=function(id)
        requests[#requests+1]="env:"..id
        return saved[id] and saved[id].."\n" or nil
    end,
    last_receipt=function()
        requests[#requests+1]="receipt"
        return receipt
    end,
    daemon_status=function()
        requests[#requests+1]="pidof"
        return running
    end,
    network_hash=function()
        requests[#requests+1]="topology_hash"
        return current.."\n"
    end,
}
local first,why=probe.capture(adapter)
ok(first~=nil,"initial_capture")
same(why,nil,"no_error")
same(first.schema,1,"schema")
same(first.group,"isp_vlan","correct_group")
same(first.no_device_write,true,"read_only")
same(first.no_reboot,true,"no_reboot")
same(first.no_firmware_commit,true,"no_commit")
same(first.contains_registration_secret,false,"no_secrets")
same(first.source_only_not_hardware_qualified,true,"not_hardware_qualified")
same(first.daemon.running,true,"daemon_present_only")
same(first.daemon.proves_translation_active,false,"daemon_not_proof")
same(first.last_reconciliation.present,true,"last_receipt_valid")
same(first.last_reconciliation.topology_matches_record,true,"topology_unchanged")
same(first.last_reconciliation.topology_match_proves_rules_current,false,
     "hash_not_tc_proof")
same(first.last_reconciliation.current_traffic_control_rules_verified,false,
     "no_tc_proof")
same(first.summary.live_tc_rules_verified,0,"zero_live_rules_verified")
same(first.internet_path_verified,false,"not_wan_qualified")
same(#requests,6,"three_fixed_env_and_receipt_daemon_hash")
for _,id in ipairs(model.fields) do
    local field=assert(first.fields[id])
    same(field.id,id,"field_identity_"..id)
    same(field.observed_effective_value,nil,"never_fabricate_tc_"..id)
    same(field.runtime_effect_proven,false,"no_effect_proof_"..id)
    same(field.reboot_persistence_proven,false,"no_reboot_proof_"..id)
    same(field.recovery_proven,false,"no_recovery_proof_"..id)
    same(field.hardware_qualified,false,"no_complete_qualification_"..id)
end
same(first.fields.fix_vlans.saved_value,"1","mode_read")
same(first.fields.fix_vlans.source_default,"1","mode_source_default")
same(first.fields.fix_vlans.last_recorded_value,nil,"mode_not_guessed_from_receipt")
same(first.fields.internet_vlan.saved_value,"200","internet_saved")
same(first.fields.internet_vlan.last_recorded_value,"200","internet_last_recorded")
same(first.fields.internet_vlan.saved_to_last_recorded,"match","internet_record_match")
same(first.fields.services_vlan.saved_value,"36","services_saved")
same(first.fields.services_vlan.last_recorded_value,"36","services_last_recorded")
same(first.fields.services_vlan.saved_to_last_recorded,"match","services_record_match")
same(first.summary.saved_match_recorded,2,"two_last_record_matches")
for _,id in ipairs(requests) do
    ok(not id:find("reg_id",1,true) and
       not id:find("loid",1,true) and
       not id:find("lpwd",1,true) and
       not id:find("gpon_sn",1,true) and
       not id:find("root_pwhash",1,true),"no_authentication_read")
end

-- Topology changes cannot be passed off as still matching the receipt.
current=TWO
local changed=assert(probe.capture(adapter))
same(changed.last_reconciliation.present,true,"old_receipt_readable")
same(changed.last_reconciliation.topology_matches_record,false,
     "changed_topology_detected")
same(changed.fields.internet_vlan.runtime_effect_proven,false,
     "changed_topology_not_effect")
current=ONE

-- A process failing or exiting means only no process signal, not proof
-- that local Internet service or VLAN rules are absent.
running=false
local missing=assert(probe.capture(adapter))
same(missing.daemon.running,false,"daemon_absent_observed")
same(missing.internet_path_verified,false,"no_WAN_inference")
same(missing.fields.internet_vlan.runtime_effect_proven,false,
     "daemon_absence_no_TC_proof")
running=true

-- Disabled, automatic or hook-only mode is saved input, never proof of
-- active translation rules, and a previous automatic receipt can be stale.
saved.fix_vlans="0"
local off=assert(probe.capture(adapter))
same(off.fields.fix_vlans.saved_value,"0","disabled_mode")
same(off.fields.fix_vlans.runtime_effect_proven,false,"disabled_not_tc_proof")
saved.fix_vlans="2"
local hooked=assert(probe.capture(adapter))
same(hooked.fields.fix_vlans.saved_value,"2","hook_mode")
same(hooked.fields.fix_vlans.last_recorded_value,nil,"hook_not_native_receipt")
saved.fix_vlans="1"

-- Missing saved VLAN values are not zero-filled except the documented
-- *source default hint* for Internet VLAN; services must be detected.
saved.internet_vlan=nil
saved.services_vlan=nil
local defaults=assert(probe.capture(adapter))
same(defaults.fields.internet_vlan.saved_value,nil,"internet_override_unset")
same(defaults.fields.internet_vlan.source_default,"0","internet_default_hint")
same(defaults.fields.services_vlan.saved_value,nil,"services_override_unset")
same(defaults.fields.services_vlan.source_default,nil,"services_default_unknown")
same(defaults.fields.services_vlan.saved_to_last_recorded,"unverified",
     "unset_saved_no_fake_match")
saved.internet_vlan="200"
saved.services_vlan="36"

-- Saved value mismatch must remain evident without stating actual
-- forwarding has changed.
saved.internet_vlan="201"
local drift=assert(probe.capture(adapter))
same(drift.fields.internet_vlan.saved_to_last_recorded,"mismatch",
     "record_mismatch")
same(drift.summary.saved_drift_from_recorded,1,"record_drift_counter")
same(drift.fields.internet_vlan.runtime_effect_proven,false,
     "drift_not_proof_of_rule")
saved.internet_vlan="200"

-- Reject invalid mode, VLAN range, leading zeros, control characters.
for _,value in ipairs({"3","-1","01","on","99999","1\nBAD"}) do
    saved.fix_vlans=value
    local bad=assert(probe.capture(adapter))
    same(bad.fields.fix_vlans.saved_value,nil,"invalid_mode_"..value)
    same(bad.fields.fix_vlans.runtime_effect_proven,false,
         "invalid_mode_no_false_effect")
end
saved.fix_vlans="1"
for _,value in ipairs({"4096","-1","0200","0x20","abc"}) do
    saved.internet_vlan=value
    local bad=assert(probe.capture(adapter))
    same(bad.fields.internet_vlan.saved_value,nil,"invalid_internet_"..value)
end
saved.internet_vlan="200"
saved.services_vlan="0"
local zero=assert(probe.capture(adapter))
same(zero.fields.services_vlan.saved_value,nil,"service_zero_not_supported")
saved.services_vlan="36"

-- Treat native receipt as data only, and require all three safe keys.
local record,reason=model.parse_last_reconciliation(receipt)
ok(record~=nil,"native_valid_receipt")
same(reason,nil,"valid_receipt_no_error")
same(record.internet_vlan,"200","record_internet")
same(record.services_vlan,"36","record_services")
same(record.topology_hash,ONE,"record_hash")
record,reason=model.parse_last_reconciliation("INTERNET_VLAN=200\nSERVICES_VLAN=36\n")
same(record,nil,"incomplete_receipt")
same(reason,"incomplete_native_receipt","incomplete_reason")
record,reason=model.parse_last_reconciliation(receipt.."INTERNET_VLAN=200\n")
same(record,nil,"duplicate_receipt_rejected")
same(reason,"duplicate_native_receipt_key","duplicate_reason")
record,reason=model.parse_last_reconciliation(receipt:gsub("STATE_HASH="..ONE,
                                     "STATE_HASH=bad"))
same(record,nil,"bad_hash_rejected")
record,reason=model.parse_last_reconciliation(receipt:gsub("SERVICES_VLAN=36",
                                      "SERVICES_VLAN=200"))
same(record,nil,"same_internet_and_services_rejected")
record,reason=model.parse_last_reconciliation(string.rep("x",4097))
same(record,nil,"oversized_receipt_rejected")
record,reason=model.parse_last_reconciliation(receipt:gsub("INTERNET_VLAN=200",
                                      "INTERNET_VLAN=200;rm"))
same(record,nil,"injected_assignment_rejected")
-- Unknown raw lines are never executed or exported. Parsed fields remain
-- non-secret fixed-name evidence, never a shell source operation.
record,reason=model.parse_last_reconciliation(
    receipt.."\nEXTRA_COMMENT=this_is_never_executed\n")
ok(record~=nil,"unused_line_never_executed")

-- An absent or unreadable receipt must not be reconstructed from
-- the saved boot env or fabricated into successful TC rules.
local last=adapter.last_receipt
local hashes=0
adapter.last_receipt=function() return nil end
local hashFn=adapter.network_hash
adapter.network_hash=function()
    hashes=hashes+1
    return ONE
end
local absent=assert(probe.capture(adapter))
same(absent.last_reconciliation.present,false,"absent_receipt")
same(absent.last_reconciliation.topology_matches_record,nil,
     "no_hash_comparison_without_receipt")
same(absent.fields.internet_vlan.last_recorded_value,nil,
     "absence_not_filled_from_saved")
same(hashes,0,"no_expensive_hash_on_missing_receipt")
adapter.last_receipt=last
adapter.network_hash=hashFn

-- Current topology hash failure and daemon read failure are unknown.
adapter.network_hash=function() error("synthetic timeout") end
local nohash=assert(probe.capture(adapter))
same(nohash.last_reconciliation.present,true,"receipt_still_present")
same(nohash.last_reconciliation.topology_matches_record,nil,
     "failed_hash_stays_unknown")
adapter.network_hash=hashFn
local olddaemon=adapter.daemon_status
adapter.daemon_status=function()error("synthetic pidof failure")end
local nodaemon=assert(probe.capture(adapter))
same(nodaemon.daemon.running,nil,"failed_pidof_unknown")
adapter.daemon_status=olddaemon

local notvalid,why=model.inspect(nil)
same(notvalid,nil,"invalid_source")
same(why,"invalid_vlan_source","invalid_source_reason")
notvalid,why=probe.capture({})
same(notvalid,nil,"invalid_probe")
same(why,"invalid_readonly_vlan_adapter","invalid_probe_reason")

ok(tests>=105,"fixture_substantial")
print("AOTT_C011_ISP_VLAN_FIXTURE_PASS checks="..tests)
