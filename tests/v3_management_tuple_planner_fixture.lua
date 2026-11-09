local root=assert(arg[1],"overlay lua root required")
package.path=root.."/?.lua;"..package.path

local function ip(a,b,c,d) return table.concat({a,b,c,d},".") end
local function mac(a,b,c,d,e,f) return table.concat({a,b,c,d,e,f},":") end
local transition=require "8311.vlan_transition"

local function snapshot()
 return {
  network={
   lct={type="interface",options={
    ifname="eth0_0_1_lct",proto="static",auto="1",
    macaddr=mac('02','11','22','33','44','55'),
    ipaddr=ip('192','0','2','1'),netmask=ip('255','255','255','0'),
    gateway=ip('192','0','2','254'),dns=ip('192','0','2','53'),
   }},
  },
  firewall={
   ["@zone[0]"]={type="zone",options={
    name="lan",network={"lan","lct"},input="ACCEPT",
    output="ACCEPT",forward="ACCEPT",
   }},
  },
 }
end
local checks=0
local function eq(a,b,label)
 checks=checks+1
 assert(a==b,"MANAGEMENT_TUPLE_FIXTURE:"..label..
        " expected="..tostring(b).." got="..tostring(a))
end
local function truth(v,label) eq(not not v,true,label) end

local request={
 vlan=123,ipaddr=ip('198','51','100','10'),netmask=ip('255','255','255','0'),
 gateway=ip('198','51','100','1'),dns_server=ip('198','51','100','53'),
 lct_mac=mac('02','AA','BB','CC','DD','EE'),
}
local handle,why=transition.prepare_management(
 snapshot(),request,"eth0_0_1_lct","lan")
assert(handle,why)
local projection=assert(transition.fixture_projection(handle,"offline_synthetic"))
local after=projection.after
eq(after.network.lct.options.ipaddr,nil,"tagged_lct_ip_removed")
eq(after.network.lct.options.netmask,nil,"tagged_lct_mask_removed")
eq(after.network.lct.options.gateway,nil,"tagged_lct_gateway_removed")
eq(after.network.lct.options.dns,nil,"tagged_lct_dns_removed")
eq(after.network.lct.options.macaddr,mac('02','AA','BB','CC','DD','EE'),"tagged_lct_mac")
eq(after.network.mgmt.type,"interface","tagged_mgmt_interface")
eq(after.network.mgmt.options.ifname,"mgmt","tagged_mgmt_ifname")
eq(after.network.mgmt.options.ipaddr,ip('198','51','100','10'),"tagged_ip")
eq(after.network.mgmt.options.netmask,ip('255','255','255','0'),"tagged_mask")
eq(after.network.mgmt.options.gateway,ip('198','51','100','1'),"tagged_gateway")
eq(after.network.mgmt.options.dns,ip('198','51','100','53'),"tagged_dns")
eq(after.network.mgmt.options.macaddr,mac('02','AA','BB','CC','DD','EE'),"tagged_mac")
eq(after.network.mgmt.options.aott_owner,"aott_c014_v1","tagged_owner")
eq(after.network.lct_vlan.type,"device","tagged_device_type")
eq(after.network.lct_vlan.options.vid,"123","tagged_vlan")
eq(after.network.lct_vlan.options.aott_owner,"aott_c014_v1","tagged_device_owner")
local members=after.firewall["@zone[0]"].options.network
local joined=type(members)=="table" and table.concat(members," ") or members
truth(joined:find("lct",1,true)~=nil,"lan_keeps_lct")
truth(joined:find("mgmt",1,true)~=nil,"lan_adds_mgmt")
truth(#projection.operations>0,"tagged_has_operations")

local summary=assert(transition.redacted_summary(handle,"production_preview"))
eq(summary.contains_configuration_values,false,"preview_redacted")
eq(summary.production_write_allowed,false,"preview_not_writer")
eq(summary.changes_required,true,"preview_changes")
truth(summary.network_operations>0,"preview_network_ops")

-- Return to untagged while changing every management value again.
local h2,why2=transition.prepare_management(after,{
 vlan=0,ipaddr=ip('203','0','113','20'),netmask=ip('255','255','255','128'),
 gateway=ip('203','0','113','1'),dns_server=ip('203','0','113','53'),
 lct_mac=mac('02','10','20','30','40','50'),
},"eth0_0_1_lct","lan")
assert(h2,why2)
local p2=assert(transition.fixture_projection(h2,"offline_synthetic"))
local untag=p2.after
eq(untag.network.mgmt,nil,"untagged_mgmt_removed")
eq(untag.network.lct_vlan,nil,"untagged_vlan_device_removed")
eq(untag.network.lct.options.ipaddr,ip('203','0','113','20'),"untagged_ip")
eq(untag.network.lct.options.netmask,ip('255','255','255','128'),"untagged_mask")
eq(untag.network.lct.options.gateway,ip('203','0','113','1'),"untagged_gateway")
eq(untag.network.lct.options.dns,ip('203','0','113','53'),"untagged_dns")
eq(untag.network.lct.options.macaddr,mac('02','10','20','30','40','50'),"untagged_mac")
local um=untag.firewall["@zone[0]"].options.network
local uj=type(um)=="table" and table.concat(um," ") or um
truth(uj:find("lct",1,true)~=nil,"untagged_lct_present")
truth(uj:find("mgmt",1,true)==nil,"untagged_mgmt_absent")

-- Blank optional gateway/DNS means removal, not an invented value.
local h3=assert(transition.prepare_management(snapshot(),{
 vlan=0,gateway="",dns_server=""
},"eth0_0_1_lct","lan"))
local p3=assert(transition.fixture_projection(h3,"offline_synthetic"))
eq(p3.after.network.lct.options.gateway,nil,"blank_gateway_removed")
eq(p3.after.network.lct.options.dns,nil,"blank_dns_removed")

local function refused(request,expected)
 local h,e=transition.prepare_management(snapshot(),request,"eth0_0_1_lct","lan")
 eq(h,nil,"refused_"..expected)
 eq(e,expected,"reason_"..expected)
end
refused({vlan=0,dns_server=ip('999','1','1','1')},"management_ipv4_profile_unqualified")
refused({vlan=0,ipaddr=ip('224','0','0','1')},"management_ipv4_profile_unqualified")
refused({vlan=0,lct_mac="not-a-mac"},"management_mac_profile_unqualified")
refused({vlan=4095},"vlan_not_explicitly_supported")
refused({vlan=0,unexpected="x"},"management_request_field_invalid")

truth(checks>=40,"coverage")
print("AOTT_V3_MANAGEMENT_TUPLE_PLANNER_PASS checks="..checks)


-- V3 overlay production execution remains private and stale-state bound.
local function deep(t)
 if type(t)~="table" then return t end
 local r={};for k,v in pairs(t) do r[k]=deep(v) end;return r
end
local function apply_op(state,op)
 local verb,arg=op[1],op[2]
 if verb=="commit" then return true end
 local lhs,value=arg:match("^([^=]+)=(.*)$")
 if not lhs then lhs=arg end
 local pkg,section,option=lhs:match("^([^.]+)%.([^.]+)%.(.+)$")
 if not pkg then pkg,section=lhs:match("^([^.]+)%.(.+)$") end
 if pkg~="network" and pkg~="firewall" then return false end
 local package=state[pkg]
 if verb=="delete" then
   if option then
     if package[section] then package[section].options[option]=nil end
   else package[section]=nil end
   return true
 elseif verb=="set" then
   if option then
     if not package[section] then return false end
     package[section].options[option]=value
   else
     package[section]={type=value,options={}}
   end
   return true
 elseif verb=="add_list" then
   if not option or not package[section] then return false end
   local current=package[section].options[option]
   if current==nil then current={}
   elseif type(current)~="table" then return false end
   current[#current+1]=value
   package[section].options[option]=current
   return true
 end
 return false
end

local state=snapshot()
local ph=assert(transition.prepare_management(state,request,"eth0_0_1_lct","lan"))
local adapter={
 production_runtime=true,
 snapshot=function() return deep(state) end,
 persisted_snapshot=function() return deep(state) end,
 command=function(op) return apply_op(state,op) end,
}
local receipt,receiptwhy=transition.verify_staged(ph,adapter,"production_runtime")
assert(receipt,receiptwhy)
eq(receipt.status,"MANAGEMENT_UCI_APPLIED_VERIFIED","production_status")
eq(receipt.production_applied,true,"production_applied")
eq(receipt.contains_configuration_values,false,"production_receipt_redacted")
eq(state.network.mgmt.options.ipaddr,ip('198','51','100','10'),"production_ip_applied")
eq(state.network.lct_vlan.options.vid,"123","production_vlan_applied")

local stale=snapshot()
local sh=assert(transition.prepare_management(stale,request,"eth0_0_1_lct","lan"))
stale.network.lct.options.hostname="unexpected"
local sr,se=transition.verify_staged(sh,{
 production_runtime=true,
 snapshot=function() return deep(stale) end,
 persisted_snapshot=function() return deep(stale) end,
 command=function() error("stale candidate must not mutate") end,
},"production_runtime")
eq(sr,nil,"stale_production_refused")
eq(se,"stale_candidate_revision","stale_production_reason")

local guarded=snapshot()
local gh=assert(transition.prepare_management(guarded,request,"eth0_0_1_lct","lan"))
local gr,ge=transition.verify_staged(gh,{
 snapshot=function() return deep(guarded) end,
 persisted_snapshot=function() return deep(guarded) end,
 command=function() return true end,
},"production_runtime")
eq(gr,nil,"production_adapter_capability_required")
eq(ge,"private_candidate_adapter_required","production_adapter_reason")
