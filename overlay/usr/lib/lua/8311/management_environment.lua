-- AoTT-8311 V3 lossless management boot-environment snapshot/restore.
-- Scope is fixed to six management keys. Present-empty is refused because the
-- native fwenv wrapper intentionally maps empty values to key deletion.
local reader=require "8311.native_management_reader"
local tools=require "8311.tools"
local M={}
local KEYS={"ipaddr","netmask","gateway","dns_server","lct_mac","lct_vlan"}
local ALLOWED={};for _,key in ipairs(KEYS) do ALLOWED[key]=true end
local HEADER="AOTT-MANAGEMENT-ENV-1"

local function safe_text(value)
    return type(value)=="string" and #value<=128 and
        not value:find("[%z\1-\31\127]")
end
local function validate_records(records)
    if type(records)~="table" or getmetatable(records)~=nil then return nil end
    local out={}
    for key in pairs(records) do if not ALLOWED[key] then return nil end end
    for _,key in ipairs(KEYS) do
        local row=records[key]
        if type(row)~="table" or getmetatable(row)~=nil then return nil end
        if row.state=="unset" and row.value==nil then
            out[key]={state="unset"}
        elseif row.state=="value" and safe_text(row.value) and row.value~="" then
            out[key]={state="value",value=row.value}
        else
            return nil
        end
    end
    return out
end

function M.encode(records)
    records=validate_records(records)
    if not records then return nil,"management_environment_snapshot_invalid" end
    local rows={HEADER}
    for _,key in ipairs(KEYS) do
        local row=records[key]
        if row.state=="unset" then
            rows[#rows+1]=key.."\tunset"
        else
            rows[#rows+1]=key.."\tvalue\t"..row.value
        end
    end
    return table.concat(rows,"\n").."\n"
end

function M.decode(raw)
    if type(raw)~="string" or #raw>4096 or raw:find("[%z\1-\8\11\12\14-\31\127]") then
        return nil,"management_environment_snapshot_invalid"
    end
    local lines={}
    for line in (raw.."\n"):gmatch("(.-)\n") do
        if line~="" then lines[#lines+1]=line end
    end
    if #lines~=#KEYS+1 or lines[1]~=HEADER then
        return nil,"management_environment_snapshot_invalid"
    end
    local records={}
    for index,key in ipairs(KEYS) do
        local line=lines[index+1]
        local name,state,value=line:match("^([a-z_]+)\t([a-z]+)\t?(.*)$")
        if name~=key or records[key] then
            return nil,"management_environment_snapshot_invalid"
        end
        if state=="unset" and value=="" then records[key]={state="unset"}
        elseif state=="value" and safe_text(value) and value~="" then
            records[key]={state="value",value=value}
        else return nil,"management_environment_snapshot_invalid" end
    end
    return validate_records(records)
end

function M.snapshot()
    local handle,why=reader.read()
    if not handle then return nil,why end
    local records=reader.records(handle)
    if not records then return nil,"management_environment_read_failed" end
    local encoded,ewhy=M.encode(records)
    if not encoded then return nil,ewhy end
    return encoded,records
end

local function equal(a,b)
    for _,key in ipairs(KEYS) do
        local x,y=a[key],b[key]
        if not x or not y or x.state~=y.state or x.value~=y.value then return false end
    end
    return true
end

function M.restore(raw)
    local expected,why=M.decode(raw)
    if not expected then return nil,why end
    for _,key in ipairs(KEYS) do
        local row=expected[key]
        local ok=tools.fw_setenv_8311{key,row.state=="value" and row.value or nil}
        if ok~=true then return nil,"management_environment_restore_write_failed" end
    end
    local current,records=M.snapshot()
    if not current or not records or not equal(expected,records) then
        return nil,"management_environment_restore_readback_failed"
    end
    return {status="MANAGEMENT_ENVIRONMENT_RESTORED",fields=#KEYS,
            contains_configuration_values=false}
end

function M.request(before,request)
    local records,why=M.decode(before)
    if not records then return nil,why end
    if type(request)~="table" then return nil,"management_environment_request_invalid" end
    local values={
        ipaddr=request.ipaddr,netmask=request.netmask,gateway=request.gateway,
        dns_server=request.dns_server,lct_mac=request.lct_mac,
        lct_vlan=request.vlan and tostring(request.vlan) or nil,
    }
    for _,key in ipairs(KEYS) do
        local value=values[key]
        if type(value)~="string" or value=="" then
            if key=="gateway" or key=="dns_server" then records[key]={state="unset"}
            else return nil,"management_environment_request_incomplete" end
        else
            if not safe_text(value) then return nil,"management_environment_request_invalid" end
            records[key]={state="value",value=value}
        end
    end
    return M.encode(records)
end

function M.request_from_snapshot(raw)
    local records,why=M.decode(raw)
    if not records then return nil,why end
    local function value(key,allow_unset)
        local row=records[key]
        if row.state=="value" then return row.value end
        if allow_unset and row.state=="unset" then return "" end
        return nil
    end
    local vlan=value("lct_vlan",true)
    if vlan=="" then vlan="0" end
    if type(vlan)~="string" or not vlan:match("^%d+$") or
       tonumber(vlan)>4094 then
        return nil,"management_environment_vlan_invalid"
    end
    local request={
        vlan=tonumber(vlan),
        ipaddr=value("ipaddr",false),
        netmask=value("netmask",false),
        gateway=value("gateway",true),
        dns_server=value("dns_server",true),
        lct_mac=value("lct_mac",false),
    }
    if not request.ipaddr or not request.netmask or not request.lct_mac then
        return nil,"management_environment_snapshot_incomplete"
    end
    return request
end

function M.apply_request(before,request)
    local desired,why=M.request(before,request)
    if not desired then return nil,why end
    local target=M.decode(desired)
    for _,key in ipairs(KEYS) do
        local row=target[key]
        local ok=tools.fw_setenv_8311{key,row.state=="value" and row.value or nil}
        if ok~=true then
            M.restore(before)
            return nil,"management_environment_apply_write_failed"
        end
    end
    local current,records=M.snapshot()
    if not current or not records or current~=desired then
        M.restore(before)
        return nil,"management_environment_apply_readback_failed"
    end
    return {status="MANAGEMENT_ENVIRONMENT_APPLIED",fields=#KEYS,
            contains_configuration_values=false},desired
end

M.keys=KEYS
return M
