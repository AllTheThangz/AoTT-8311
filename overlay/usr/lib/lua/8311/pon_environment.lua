-- AoTT-8311 V3 lossless private snapshot/restore for PON/OMCI settings.
-- Encoded snapshots may contain subscriber credentials and must remain inside
-- the root-only recovery store. No caller may return snapshot contents.
local tools=require "8311.tools"
local M={}
local FIELDS={
    "gpon_sn","vendor_id","equipment_id","hw_ver","cp_hw_ver_sync",
    "sw_verA","sw_verB","fw_match_b64","fw_match_num","override_active",
    "override_commit","pon_mode","omcc_version","iop_mask","reg_id_hex",
    "loid","lpwd","mib_file","pon_slot","iphost_mac","iphost_hostname",
    "iphost_domain",
}
local SET={};for _,id in ipairs(FIELDS) do SET[id]=true end
local HEADER="AOTT-PON-ENV-1"

local function storage(id)
    return id
end
local function safe(value)
    return type(value)=="string" and #value<=1024 and
        not value:find("[%z\1-\8\11\12\14-\31\127]")
end
local function validate(records)
    if type(records)~="table" or getmetatable(records)~=nil then return nil end
    local out={}
    for id in pairs(records) do if not SET[id] then return nil end end
    for _,id in ipairs(FIELDS) do
        local row=records[id]
        if type(row)~="table" or getmetatable(row)~=nil then return nil end
        if row.state=="unset" and row.value==nil then
            out[id]={state="unset"}
        elseif row.state=="value" and safe(row.value) then
            out[id]={state="value",value=row.value}
        else return nil end
    end
    return out
end

function M.encode(records)
    records=validate(records)
    if not records then return nil,"pon_environment_snapshot_invalid" end
    local rows={HEADER}
    for _,id in ipairs(FIELDS) do
        local row=records[id]
        if row.state=="unset" then
            rows[#rows+1]=id.."\tunset"
        else
            rows[#rows+1]=id.."\tvalue\t"..row.value
        end
    end
    return table.concat(rows,"\n").."\n"
end

function M.decode(raw)
    if type(raw)~="string" or #raw>32768 or
       raw:find("[%z\1-\8\11\12\14-\31\127]") then
        return nil,"pon_environment_snapshot_invalid"
    end
    local lines={}
    for line in (raw.."\n"):gmatch("(.-)\n") do if line~="" then lines[#lines+1]=line end end
    if #lines~=#FIELDS+1 or lines[1]~=HEADER then
        return nil,"pon_environment_snapshot_invalid"
    end
    local records={}
    for index,id in ipairs(FIELDS) do
        local name,state,value=lines[index+1]:match("^([A-Za-z0-9_]+)\t([a-z]+)\t?(.*)$")
        if name~=id or records[id] then return nil,"pon_environment_snapshot_invalid" end
        if state=="unset" and value=="" then records[id]={state="unset"}
        elseif state=="value" and safe(value) then records[id]={state="value",value=value}
        else return nil,"pon_environment_snapshot_invalid" end
    end
    return validate(records)
end

function M.snapshot()
    local values,why=tools.fwenv_read_all()
    if not values then return nil,why end
    local records={}
    for _,id in ipairs(FIELDS) do
        local value=values["8311_"..storage(id)]
        records[id]=value~=nil and {state="value",value=value} or {state="unset"}
    end
    local encoded,ewhy=M.encode(records)
    if not encoded then return nil,ewhy end
    return encoded,records
end

local function apply_records(records)
    records=validate(records)
    if not records then return nil,"pon_environment_snapshot_invalid" end
    for _,id in ipairs(FIELDS) do
        local row=records[id]
        local ok=tools.fw_setenv_8311{
            storage(id),row.state=="value" and row.value or nil
        }
        if ok~=true then return nil,"pon_environment_write_failed" end
    end
    local current,current_records=M.snapshot()
    if not current or not current_records then return nil,"pon_environment_readback_failed" end
    for _,id in ipairs(FIELDS) do
        local a,b=records[id],current_records[id]
        if a.state~=b.state or a.value~=b.value then
            return nil,"pon_environment_readback_failed"
        end
    end
    return true
end

function M.restore(raw)
    local records,why=M.decode(raw)
    if not records then return nil,why end
    local ok,ewhy=apply_records(records)
    if not ok then return nil,ewhy end
    return {status="PON_ENVIRONMENT_RESTORED",fields=#FIELDS,
            contains_configuration_values=false}
end

function M.request(before,changes)
    local records,why=M.decode(before)
    if not records then return nil,why end
    if type(changes)~="table" or getmetatable(changes)~=nil then
        return nil,"pon_environment_request_invalid"
    end
    local count=0
    for id,value in pairs(changes) do
        if not SET[id] or type(value)~="string" or not safe(value) then
            return nil,"pon_environment_request_invalid"
        end
        count=count+1
        records[id]=value=="" and {state="unset"} or {state="value",value=value}
    end
    if count<1 or count>#FIELDS then return nil,"pon_environment_request_empty" end
    return M.encode(records)
end

function M.apply_request(before,changes)
    local desired,why=M.request(before,changes)
    if not desired then return nil,why end
    local target=M.decode(desired)
    local ok,ewhy=apply_records(target)
    if not ok then
        M.restore(before)
        return nil,ewhy
    end
    return {status="PON_ENVIRONMENT_APPLIED",fields=#FIELDS,
            contains_configuration_values=false},desired
end

M.fields=FIELDS
M.field_set=SET
M.storage_id=storage
return M
