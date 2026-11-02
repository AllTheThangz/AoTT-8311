-- C-011 exact native builtin TC rules: read-only Lua model and gates.
-- Synthetic values, no device commands and no provider identifiers.
local dir=assert(arg[1],"overlay Lua root required")
package.path=dir.."/?.lua;"..package.path
local model=require "8311.effective_vlan_state"
local probe=require "8311.effective_vlan_probe"

local checks=0
local function ok(value,name)
    checks=checks+1
    assert(value,"TC_READONLY_FIXTURE_FAILED:"..name)
end
local function equal(a,b,name)ok(a==b,name)end

local HASH=string.rep("a",64)
local OTHER=string.rep("b",64)
local saved={
    fix_vlans="1",internet_vlan="200",services_vlan="36",
}
local receipt=table.concat({
    "# Native source receipt for synthetic test only",
    "UNICAST_VLAN=100",
    "MULTICAST_GEM=",
    "INTERNET_PMAP=pmapper4354",
    'INTERNET_GEMS="gem12 gem13"',
    "SERVICES_PMAP=pmapper57603",
    "SERVICES_GEMS=",
    "INTERNET_VLAN=200",
    "SERVICES_VLAN=36",
    "DEFAULT_SERVICES_VLAN=100",
    "STATE_HASH="..HASH,
    "",
},"\n")

local plan,reason=model.parse_rule_plan(receipt)
ok(plan~=nil,"valid_plan")
equal(reason,nil,"no_plan_error")
equal(plan.internet_vlan,"200","internet_vlan")
equal(plan.services_vlan,"36","services_vlan")
equal(plan.unicast_vlan,"100","OLT_unicast")
equal(plan.internet_pmap,"pmapper4354","internet_pmap")
equal(plan.services_pmap,"pmapper57603","services_pmap")
equal(plan.original_services_vlan,"100","OLT_services_vlan")
equal(plan.multicast,"0","no_multicast")
equal(plan.expected_rule_count,8,"tagged_two_pmaps_eight_rules")
equal(plan.topology_hash,HASH,"topology_hash")
ok(model.strict_rule_evidence("VERIFIED_RULES=8\n",plan),"strict_rule_positive")
for _,bad in ipairs({
    "VERIFIED_RULES=7\n","VERIFIED_RULES=9\n","VERIFIED_RULES=8",
    "VERIFIED_RULES=8\nERROR\n","VERIFIED_RULES=8\r\n",
    "VERIFIED_RULES=8; echo SUCCESS\n","VERIFIED_RULES=08\n",
}) do
    ok(not model.strict_rule_evidence(bad,plan),"strict_rule_negative")
end

local seen={}
local active_receipt=receipt
local network_hash=HASH
local mode="1"
local reply="VERIFIED_RULES=8\n"
local function adapter()
    return {
        environment=function(name)
            if name=="fix_vlans" then return mode.."\n" end
            return saved[name] and saved[name].."\n" or nil
        end,
        last_receipt=function()
            seen.receipts=(seen.receipts or 0)+1
            return active_receipt
        end,
        daemon_status=function()return true end,
        network_hash=function()
            seen.hashes=(seen.hashes or 0)+1
            return network_hash.."\n"
        end,
        verify_rules=function(p)
            seen.calls=(seen.calls or 0)+1
            seen.plan=p
            return reply
        end,
    }
end
local data=assert(probe.capture(adapter()))
equal(seen.calls,1,"native_tc_once")
equal(data.kernel_tc.read_attempted,true,"native_read_attempt_recorded")
equal(data.kernel_tc.full_owned_rules_match,true,"all_selected_kernel_rules_match")
equal(data.kernel_tc.verified_rules_count,8,"verified_count")
equal(data.summary.live_tc_rules_verified,8,"summary_verified_rules")
equal(data.last_reconciliation.current_traffic_control_rules_verified,
      true,"scoped_current_tc_verification")
equal(data.fields.internet_vlan.runtime_effect_proven,true,"internet_tc_proven")
equal(data.fields.internet_vlan.observed_effective_value,"200","internet_effective")
equal(data.fields.internet_vlan.observed_source,
      "independent_kernel_tc_flower_readback","internet_evidence_source")
equal(data.fields.services_vlan.runtime_effect_proven,true,"services_tc_proven")
equal(data.fields.services_vlan.observed_effective_value,"36","services_effective")
equal(data.fields.fix_vlans.runtime_effect_proven,false,"mode_not_proven")
equal(data.fields.internet_vlan.hardware_qualified,false,"no_total_hardware_qualification")
equal(data.fields.internet_vlan.recovery_proven,false,"recovery_not_proven")
equal(data.kernel_tc.proves_subscriber_internet,false,"no_WAN_claim")
equal(data.kernel_tc.proves_hardware_offload,false,"offload_not_proven")
equal(data.kernel_tc.proves_all_traffic_rules_correct,false,"other_rules_unexamined")
equal(data.internet_path_verified,false,"no_Internet_claim")
equal(data.last_reconciliation.topology_matches_record,true,"topology_verified")

seen={}
reply="VERIFIED_RULES=7\n"
local wrong=assert(probe.capture(adapter()))
equal(wrong.kernel_tc.read_attempted,true,"failed_match_still_attempted")
equal(wrong.kernel_tc.full_owned_rules_match,false,"wrong_count_rejected")
equal(wrong.fields.internet_vlan.runtime_effect_proven,false,"wrong_count_no_effect")
equal(wrong.fields.services_vlan.runtime_effect_proven,false,"wrong_count_no_services")
equal(wrong.summary.live_tc_rules_verified,0,"wrong_count_zero_proven")
reply="VERIFIED_RULES=8\nEXTRA_DATA\n"
local injected=assert(probe.capture(adapter()))
equal(injected.kernel_tc.full_owned_rules_match,false,"injected_output_rejected")
reply="VERIFIED_RULES=8\n"

-- Reconciled rule shapes still match, but a saved override has drifted.
saved.internet_vlan="201"
local mismatch=assert(probe.capture(adapter()))
equal(mismatch.kernel_tc.full_owned_rules_match,true,"kernel_receipt_rules_match")
equal(mismatch.fields.internet_vlan.runtime_effect_proven,false,
      "saved_override_drift_disqualifies_field")
equal(mismatch.fields.internet_vlan.observed_effective_value,nil,
      "saved_override_drift_does_not_claim_effect")
equal(mismatch.fields.services_vlan.runtime_effect_proven,true,
      "unrelated_services_matching_still_proven")
saved.internet_vlan="200"

-- If topology changed, native rules are never queried.
seen={}
network_hash=OTHER
local topology=assert(probe.capture(adapter()))
equal(seen.calls,nil,"topology_drift_prevents_native_read")
equal(topology.kernel_tc.full_owned_rules_match,false,"changed_topology_unknown")
equal(topology.kernel_tc.read_attempted,false,"not_attempted")
network_hash=HASH

-- Disabled/hook-only modes never invoke the built-in rule verifier.
for _,value in ipairs({"0","2"}) do
    seen={}
    mode=value
    local off=assert(probe.capture(adapter()))
    equal(seen.calls,nil,"disabled_or_custom_hook_skipped")
    equal(off.kernel_tc.full_owned_rules_match,false,
          "disabled_or_hook_mode_no_proof")
end
mode="1"

-- Bad receipts, unavailable and malformed native reads fail closed.
seen={}
active_receipt=nil
local missing=assert(probe.capture(adapter()))
equal(seen.calls,nil,"missing_receipt_no_read")
equal(seen.hashes,nil,"missing_receipt_no_topology_hash")
equal(missing.kernel_tc.full_owned_rules_match,false,"missing_receipt_not_proven")
active_receipt=receipt
seen={}
local failing=adapter()
failing.verify_rules=function()
    seen.calls=(seen.calls or 0)+1
    error("synthetic tc timeout")
end
local timeout=assert(probe.capture(failing))
equal(seen.calls,1,"failed_tc_call_attempted")
equal(timeout.kernel_tc.read_attempted,true,"failed_tc_attempt_tracked")
equal(timeout.kernel_tc.full_owned_rules_match,false,"failed_tc_not_proven")

local dup=receipt.."INTERNET_PMAP=pmapper1\n"
local parsed,err=model.parse_rule_plan(dup)
equal(parsed,nil,"duplicate_pmap_rejected")
equal(err,"duplicate_rule_plan_key","duplicate_reason")
local injection=receipt:gsub("INTERNET_PMAP=pmapper4354",
                               "INTERNET_PMAP=pmapper4354;bad")
parsed,err=model.parse_rule_plan(injection)
equal(parsed,nil,"injection_in_pmapper_rejected")
local baddefault=receipt:gsub("DEFAULT_SERVICES_VLAN=100",
                                  "DEFAULT_SERVICES_VLAN=9999")
parsed,err=model.parse_rule_plan(baddefault)
equal(parsed,nil,"invalid_OLT_services_rejected")
local samepm=receipt:gsub("SERVICES_PMAP=pmapper57603",
                               "SERVICES_PMAP=pmapper4354")
parsed,err=model.parse_rule_plan(samepm)
equal(parsed,nil,"same_pmapper_rejected")

local withmc=receipt:gsub("MULTICAST_GEM=","MULTICAST_GEM=gem513")
local multicast_plan=assert(model.parse_rule_plan(withmc))
equal(multicast_plan.expected_rule_count,9,"multicast_ninth_rule")
equal(multicast_plan.multicast,"1","multicast_present")
local untagged=receipt:gsub("INTERNET_VLAN=200","INTERNET_VLAN=0")
local untagged_plan=assert(model.parse_rule_plan(untagged))
equal(untagged_plan.expected_rule_count,7,"untagged_rule_count")
equal(untagged_plan.internet_vlan,"0","untagged_internet")
local noservice=receipt:gsub("SERVICES_PMAP=pmapper57603",
                                 "SERVICES_PMAP=")
local nosvc=assert(model.parse_rule_plan(noservice))
equal(nosvc.expected_rule_count,4,"no_services_only_internet_rules")
equal(nosvc.services_pmap,"-","no_services_placeholder")
equal(nosvc.original_services_vlan,"-","no_olt_service_placeholder")
equal(nosvc.multicast,"0","no_multicast_without_services")

ok(checks>=70,"fixture_has_sufficient_coverage")
print("AOTT_C011_TC_READONLY_FIXTURE_PASS checks="..checks)
