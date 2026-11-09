-- AoTT-8311 V3 fixed MIB applicator and readback for supported GUI fields.
local fs=require "nixio.fs"
local web=require "8311.webutil"
local mib_profile=require "8311.mib_profile"
local M={}
local DEFAULT="/etc/mibs/prx300_1U.ini"

local function path(records)
    local row=records and records.mib_file
    local p=row and row.state=="value" and row.value or DEFAULT
    if type(p)~="string" or not p:match("^/etc/mibs/[A-Za-z0-9_.-]+%.ini$") then
        return nil,"pon_mib_path_invalid"
    end
    local st=fs.lstat(p)
    if not st or st.type~="reg" or st.uid~=0 or st.gid~=0 or st.nlink~=1 or st.size>131072 then
        return nil,"pon_mib_path_unavailable"
    end
    local profile,why=mib_profile.inspect(p)
    if not profile then return nil,"pon_mib_profile_unavailable:"..tostring(why) end
    return p,nil,profile
end
local function value(records,id)
    local row=records[id]
    return row and row.state=="value" and row.value or nil
end
local function pristine(p)
    local src="/rom"..p
    local st=fs.lstat(src)
    if not st or st.type~="reg" or st.uid~=0 or st.gid~=0 or st.nlink~=1 or
       type(st.size)~="number" or st.size<1 or st.size>131072 then
        return nil,"pon_pristine_mib_unavailable"
    end
    return src
end
local function copy_field(src,dst,class,index)
    return run({"/usr/libexec/8311-mib-edit.lua","copy-field",src,dst,
                tostring(class),tostring(index)})
end
local function check_source(src,dst,class,index)
    return run({"/usr/libexec/8311-mib-edit.lua","check-field-source",src,dst,
                tostring(class),tostring(index)})
end
local function run(argv)
    local code,_,overflow=web.capture(argv,4096)
    return code==0 and not overflow
end
local function set_field(p,class,index,v)
    return run({"/usr/libexec/8311-mib-edit.lua","set-field",p,tostring(class),tostring(index),v})
end

function M.apply(records)
    local p,why,profile=path(records);if not p then return nil,why end
    local src,swhy=pristine(p);if not src then return nil,swhy end
    local vendor=value(records,"vendor_id")
    local hw=value(records,"hw_ver")
    local equipment=value(records,"equipment_id")
    local slot=value(records,"pon_slot")
    if vendor then
        if not set_field(p,6,5,vendor) or not set_field(p,256,1,vendor) then return nil,"pon_mib_vendor_apply_failed" end
    elseif not copy_field(src,p,6,5) or not copy_field(src,p,256,1) then
        return nil,"pon_mib_vendor_restore_pristine_failed"
    end
    if hw then
        if not set_field(p,256,2,hw) then return nil,"pon_mib_hw_apply_failed" end
    elseif not copy_field(src,p,256,2) then
        return nil,"pon_mib_hw_restore_pristine_failed"
    end
    if hw and value(records,"cp_hw_ver_sync")=="1" then
        if not set_field(p,6,4,hw) then return nil,"pon_mib_cp_hw_apply_failed" end
    elseif not copy_field(src,p,6,4) then
        return nil,"pon_mib_cp_hw_restore_pristine_failed"
    end
    if equipment then
        if not set_field(p,257,1,equipment) then return nil,"pon_mib_equipment_apply_failed" end
    elseif not copy_field(src,p,257,1) then
        return nil,"pon_mib_equipment_restore_pristine_failed"
    end
    if slot then
        if not profile.topology or profile.topology.slot_editable~=true then
            return nil,"pon_mib_slot_not_applicable"
        end
        if not run({"/usr/libexec/8311-mib-edit.lua","set-slot",p,slot}) then return nil,"pon_mib_slot_apply_failed" end
    elseif not run({"/usr/libexec/8311-mib-edit.lua","copy-slot",src,p}) then
        return nil,"pon_mib_slot_restore_pristine_failed"
    end
    return {status="PON_MIB_APPLIED",path=p,contains_configuration_values=false}
end

function M.verify(records)
    local p,why,profile=path(records);if not p then return nil,why end
    local src,swhy=pristine(p);if not src then return nil,swhy end
    local vendor=value(records,"vendor_id")
    local hw=value(records,"hw_ver")
    local equipment=value(records,"equipment_id")
    local slot=value(records,"pon_slot")
    local function check(class,index,v)
        return run({"/usr/libexec/8311-mib-edit.lua","check-field",p,
                    tostring(class),tostring(index),v})
    end
    local function pristine_check(class,index)
        return check_source(src,p,class,index)
    end
    if vendor then
        if not check(6,5,vendor) or not check(256,1,vendor) then
            return nil,"pon_mib_vendor_readback_failed"
        end
    elseif not pristine_check(6,5) or not pristine_check(256,1) then
        return nil,"pon_mib_vendor_pristine_readback_failed"
    end
    if hw then
        if not check(256,2,hw) then return nil,"pon_mib_hw_readback_failed" end
    elseif not pristine_check(256,2) then
        return nil,"pon_mib_hw_pristine_readback_failed"
    end
    if hw and value(records,"cp_hw_ver_sync")=="1" then
        if not check(6,4,hw) then return nil,"pon_mib_cp_hw_readback_failed" end
    elseif not pristine_check(6,4) then
        return nil,"pon_mib_cp_hw_pristine_readback_failed"
    end
    if equipment then
        if not check(257,1,equipment) then return nil,"pon_mib_equipment_readback_failed" end
    elseif not pristine_check(257,1) then
        return nil,"pon_mib_equipment_pristine_readback_failed"
    end
    if slot then
        if not profile.topology or profile.topology.slot_editable~=true then
            return nil,"pon_mib_slot_not_applicable"
        end
        if not run({"/usr/libexec/8311-mib-edit.lua","check-slot",p,slot}) then
            return nil,"pon_mib_slot_readback_failed"
        end
    elseif not run({"/usr/libexec/8311-mib-edit.lua","check-slot-source",src,p}) then
        return nil,"pon_mib_slot_pristine_readback_failed"
    end
    return {status="PON_MIB_LOCAL_VERIFIED",path=p,
            identity_values_redacted=true,contains_configuration_values=false}
end
return M
