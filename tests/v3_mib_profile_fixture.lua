local lua_root=assert(arg[1],"overlay lua root required")
local rootfs=assert(arg[2],"vendor rootfs required")
package.path=lua_root.."/?.lua;"..package.path
package.preload["nixio.fs"]=function() return {} end

local function map(path)
    assert(type(path)=="string" and path:match("^/etc/mibs/"),"fixture path scope")
    return rootfs..path
end
local adapter={}
function adapter.lstat(path)
    local f=io.open(map(path),"rb")
    if not f then return nil end
    local size=f:seek("end")
    f:close()
    return {type="reg",uid=0,gid=0,nlink=1,size=size}
end
function adapter.readfile(path,max)
    local f=io.open(map(path),"rb")
    if not f then return nil end
    local data=f:read("*a")
    f:close()
    if max and #data>max then return data:sub(1,max) end
    return data
end

local mib=require "8311.mib_profile"
local expected={
    prx300_1U={variant="generic",kind="single_uni",uni=1,tcont=16,pq=136,sched=16,iphost=1,veip=0,slot=true},
    prx300_1U_telus={variant="telus",kind="single_uni",uni=1,tcont=16,pq=136,sched=16,iphost=1,veip=0,slot=true},
    prx300_1V={variant="generic",kind="single_uni_plus_veip",uni=1,tcont=16,pq=136,sched=16,iphost=0,veip=1,slot=true},
    prx300_1V_32tcont={variant="32tcont",kind="veip",uni=0,tcont=32,pq=264,sched=32,iphost=1,veip=1,slot=false},
    prx300_1V_bell={variant="bell",kind="veip",uni=0,tcont=8,pq=72,sched=16,iphost=1,veip=1,slot=false},
    prx300_2U={variant="generic",kind="multi_uni",uni=2,tcont=16,pq=144,sched=16,iphost=1,veip=0,slot=false},
    prx300_2U_voip={variant="voip",kind="multi_uni",uni=2,tcont=16,pq=144,sched=16,iphost=2,veip=0,slot=false},
}
local checks=0
local function same(a,b,label)
    checks=checks+1
    assert(a==b,"MIB_PROFILE_FIXTURE:"..label.." expected="..tostring(b).." got="..tostring(a))
end
for name,e in pairs(expected) do
    local p=assert(mib.inspect("/etc/mibs/"..name..".ini",adapter))
    same(p.schema,1,name.."_schema")
    same(p.variant_hint,e.variant,name.."_variant")
    same(p.profile_kind,e.kind,name.."_kind")
    same(p.topology.physical_uni_count,e.uni,name.."_uni")
    same(p.topology.tcont_me262_count,e.tcont,name.."_tcont")
    same(p.topology.priority_queue_me277_count,e.pq,name.."_pq")
    same(p.topology.traffic_scheduler_me278_count,e.sched,name.."_sched")
    same(p.topology.iphost_me134_count,e.iphost,name.."_iphost")
    same(p.topology.veip_me329_count,e.veip,name.."_veip")
    same(p.topology.slot_editable,e.slot,name.."_slot_editable")
    same(p.applicability.iphost_identity,e.iphost>0,name.."_iphost_app")
    same(p.applicability.pon_slot,e.slot,name.."_slot_app")
    same(p.hardware_qualified,false,name.."_hardware")
    same(p.olt_compatibility_proven,false,name.."_olt")
    same(p.contains_subscriber_values,false,name.."_privacy")
end

local one=assert(mib.inspect("/etc/mibs/prx300_1U.ini",adapter))
same(one.defaults.vendor_id,"INTC","1U_vendor_default")
same(one.defaults.pon_slot,"1","1U_slot_default")
same(one.applicability.vendor_id,true,"1U_vendor_edit")
same(one.applicability.hw_ver,true,"1U_hw_edit")
same(one.applicability.equipment_id,true,"1U_equipment_edit")
same(one.applicability.software_reporting,true,"1U_sw_edit")

local multi=assert(mib.inspect("/etc/mibs/prx300_2U.ini",adapter))
local ok,err=mib.validate_for_configuration(multi,
    {pon_slot="1"},{mib_file=true})
same(ok,nil,"multi_profile_switch_requires_slot_clear")
same(type(err.pon_slot),"string","multi_slot_error")
ok,err=mib.validate_for_configuration(multi,{pon_slot="1"},{hostname=true})
same(ok,true,"unrelated_change_preserves_existing_slot")
same(err,nil,"unrelated_no_error")

local noip=assert(mib.inspect("/etc/mibs/prx300_1V.ini",adapter))
ok,err=mib.validate_for_configuration(noip,
    {pon_slot="1",iphost_hostname="x"},{iphost_hostname=true})
same(ok,nil,"no_iphost_reject_change")
same(type(err.iphost_hostname),"string","no_iphost_error")

local v32=assert(mib.inspect("/etc/mibs/prx300_1V_32tcont.ini",adapter))
same(v32.topology.slot_reason,"veip_profile_no_physical_uni_slot_mapping","32t_slot_reason")
same(v32.topology.tcont_me262_count,32,"32t_explicit")

local bad,why=mib.inspect("/etc/passwd",adapter)
same(bad,nil,"path_escape_refused")
same(why,"mib_profile_path_invalid","path_escape_reason")

assert(checks>=110,"coverage")
print("AOTT_V3_MIB_PROFILE_PASS checks="..checks)
