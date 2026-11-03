-- C-011 ten OMCI-reporting field readbacks, synthetic data only.
-- No PON identity, firmware image mutation, network or device access.
local source=assert(arg[1],"Source Lua module root required")
package.path=source.."/?.lua;"..package.path
local state=require "8311.effective_reporting_state"
local probe=require "8311.effective_reporting_probe"
local checks=0
local function ok(condition,why)
    checks=checks+1
    assert(condition,"C011_REPORTING_FIXTURE_FAILED:"..why)
end
local function eq(a,b,why) ok(a==b,why) end

local expected={
    "equipment_id","hw_ver","cp_hw_ver_sync","sw_verA","sw_verB",
    "fw_match_b64","fw_match_num","override_active","override_commit",
    "pon_slot",
}
for i,id in ipairs(expected) do
    eq(state.fields[i],id,"fixed_field_order_"..id)
    eq(state.field_set[id],true,"field_in_whitelist_"..id)
end
eq(#state.fields,10,"ten_noncredential_fields")
eq(state.field_set.root_pwhash,nil,"no_root_hash")
eq(state.field_set.reg_id_hex,nil,"no_registration_password")
eq(state.field_set.loid,nil,"no_subscriber_LOID")
eq(state.field_set.gpon_sn,nil,"no_OLT_serial")
eq(state.field_set.iphost_mac,nil,"no_iphost_mac")
eq(state.field_set.vendor_id,nil,"no_vendor_identity")

local synthetic={
    equipment_id="MODEL_X",hw_ver="HW1",
    cp_hw_ver_sync="1",sw_verA="v2.8.3",sw_verB="v2.8.4",
    fw_match_b64="KGFiKyk=",fw_match_num="1",
    override_active="B",override_commit="A",pon_slot="1",
}
local image_labels={A="v2.8.3",B="other_version"}
local requests={}
local adapter={
    environment=function(id)
        requests[#requests+1]="env:"..id
        return synthetic[id].."\n"
    end,
    image_label=function(bank)
        requests[#requests+1]="img:"..bank
        return image_labels[bank].."\n"
    end,
}
local report,reason=probe.capture(adapter)
ok(report~=nil,"captured_report")
eq(reason,nil,"no_error")
eq(report.group,"omci_reporting_noncredential","group")
eq(report.schema,1,"schema")
eq(report.no_registration_secret_read,true,"never_read_registration")
eq(report.no_subscriber_identity_exported,true,"no_OLT_identity")
eq(report.no_raw_environment_value_exported,true,"no_boot_env_dump")
eq(report.no_firmware_commit,true,"never_commit_bank")
eq(report.actual_boot_bank_verified,false,"reported_bank_not_boot")
eq(report.proves_subscriber_internet,false,"no_WAN_claim")
eq(report.source_only_not_hardware_qualified,true,"not_hardware_verified")
eq(report.summary.source_fields,10,"source_count")
eq(report.summary.source_present,10,"ten_present")
eq(report.summary.source_format_valid,10,"ten_format_valid")
eq(report.summary.source_format_invalid,0,"none_invalid")
eq(report.summary.image_labels_compared,2,"two_image_labels_comparable")
eq(report.summary.image_labels_matching,1,"one_label_matches")
eq(report.summary.reporting_runtime_effects_verified,0,"zero_MIB_effects")
eq(report.summary.hardware_qualified,0,"zero_board_qualification")
eq(report.fields.sw_verA.reported_image_to_boot_label,"labels_match",
   "A_reported_and_stored_label_match")
eq(report.fields.sw_verB.reported_image_to_boot_label,"labels_differ",
   "B_reported_and_stored_label_drift")
eq(report.fields.override_active.reported_bank_not_actual_boot_selector,true,
   "OMCI_override_is_not_boot_bank")
eq(#requests,12,"ten_saved_plus_two_bank_labels")
for i,id in ipairs(expected) do
    eq(requests[i],"env:"..id,"exact_environment_call_"..id)
end
eq(requests[11],"img:A","actual_A_label_requested")
eq(requests[12],"img:B","actual_B_label_requested")
for _,id in ipairs(expected) do
    local row=assert(report.fields[id])
    eq(row.id,id,"row_id_"..id)
    eq(row.source_presence,true,"row_present_"..id)
    eq(row.source_format,"valid_source_format","format_"..id)
    eq(row.raw_value_exported,false,"no_raw_"..id)
    eq(row.content_redacted,true,"redacted_"..id)
    eq(row.runtime_effect_proven,false,"runtime_not_proven_"..id)
    eq(row.omci_mib_effect_proven,false,"MIB_not_proven_"..id)
    eq(row.olt_received_reported_value_proven,false,
       "OLT_delivery_not_proven_"..id)
    eq(row.actually_flashes_or_commits_firmware,false,
       "bank_mutation_not_inferred_"..id)
    eq(row.survives_reboot_proven,false,"no_reboot_proof_"..id)
    eq(row.hardware_qualified,false,"hardware_not_qualified_"..id)
    for key,value in pairs(row) do
        if type(value)=="string" then
            ok(not value:find(synthetic[id],1,true) or
               value==id,"no_sensitive_value_"..id.."_"..key)
        end
    end
end
for _,val in ipairs({"MODEL_X","HW1","v2.8.3","v2.8.4",
                    "other_version","KGFiKyk="}) do
    for _,row in pairs(report.fields) do
        for _,value in pairs(row) do
            ok(type(value)~="string" or not value:find(val,1,true),
               "no_source_value_in_output")
        end
    end
end

local function one_bad(id,value,expected_status)
    local table={}
    for k,v in pairs(synthetic) do table[k]=v end
    table[id]=value
    local output=assert(state.inspect(table,image_labels))
    eq(output.fields[id].source_format,expected_status,
       "reject_or_accept_format_"..id.."_"..tostring(value))
    eq(output.fields[id].runtime_effect_proven,false,
       "never_prove_effect_on_format_"..id)
    return output
end
one_bad("fw_match_b64","AAA=","valid_source_format")
one_bad("fw_match_b64","QQ==","valid_source_format")
one_bad("fw_match_b64","AA","invalid_source_format")
one_bad("fw_match_b64","A===","invalid_source_format")
one_bad("fw_match_b64","ABC<>","invalid_source_format")
one_bad("fw_match_b64","QQ==\n","invalid_source_format")
one_bad("fw_match_num","0","invalid_source_format")
one_bad("fw_match_num","99","valid_source_format")
one_bad("fw_match_num","100","invalid_source_format")
one_bad("fw_match_num","01","invalid_source_format")
one_bad("pon_slot","0","invalid_source_format")
one_bad("pon_slot","254","valid_source_format")
one_bad("pon_slot","255","invalid_source_format")
one_bad("cp_hw_ver_sync","true","invalid_source_format")
one_bad("cp_hw_ver_sync","0","valid_source_format")
one_bad("sw_verA",string.rep("A",15),"invalid_source_format")
one_bad("equipment_id",string.rep("e",21),"invalid_source_format")
one_bad("override_active","C","invalid_source_format")
one_bad("override_commit","off","invalid_source_format")
local unavailable=one_bad("equipment_id","", "unavailable")
eq(unavailable.summary.source_unavailable,1,"missing_field_count")
eq(unavailable.summary.source_present,9,"remaining_present")
local bad_adapter=probe.capture({environment=function() return nil end})
eq(bad_adapter,nil,"requires_both_callback_sources")
local hostile={
    environment=function(id)
        return synthetic[id] and synthetic[id].."\n" or nil
    end,
    image_label=function(bank)
        return bank=="A" and "<script>SECRET</script>\n" or nil
    end,
}
local sanit=assert(probe.capture(hostile))
eq(sanit.fields.sw_verA.reported_image_to_boot_label,"unavailable",
   "invalid_image_label_is_not_rendered")
eq(sanit.no_raw_environment_value_exported,true,"still_redacts")

-- The actual source live adapter is tested under fixed, synthetic web
-- callbacks, with no read of any registration IDs or bank selector.
local original_capture={}
package.preload["8311.webutil"]=function()
    return {
        capture=function(argv,max)
            ok(type(max)=="number" and max<=258,"bounded_max_bytes")
            local literal=table.concat(argv," ")
            original_capture[#original_capture+1]=literal
            eq(argv[1],"/usr/bin/timeout","timeout_wrapper")
            eq(argv[4],"3","command_deadline_3s")
            eq(argv[5],"/usr/sbin/fwenv_get","exact_native_getter")
            local id=argv[#argv]
            if #argv==7 then
                eq(argv[6],"--8311","prefixed_environment")
                if synthetic[id] then return 0,synthetic[id].."\n",false end
            elseif #argv==6 then
                ok(id=="img_versionA" or id=="img_versionB",
                   "only_actual_image_version_labels")
                local bank=id:sub(-1)
                return 0,image_labels[bank].."\n",false
            end
            error("Unexpected native argument sequence")
        end
    }
end
local live=assert(probe.live_reporting())
eq(live.summary.source_format_valid,10,"live_source_formatter")
eq(#original_capture,12,"twelve_fixed_calls_only")
eq(live.no_registration_secret_read,true,"live_no_secret_calls")
for _,command in ipairs(original_capture) do
    for _,blocked in ipairs({
        "root_pwhash","gpon_sn","reg_id_hex","loid","lpwd",
        "iphost_mac","fwenv_set","bankctl","/dev/mtd",
    }) do
        ok(not command:find(blocked,1,true),
           "native_command_disallows_"..blocked)
    end
end
package.loaded["8311.webutil"]=nil
package.preload["8311.webutil"]=nil

ok(checks>=290,"fixture_size")
print("AOTT_C011_REPORTING_FIXTURE_PASS checks="..checks)
