-- AoTT-8311 C-011: portable, read-only effective device/SFP interpreter.
-- Pure Lua 5.1. No I/O, configuration writes, network access or secrets.
-- Configured virtual EEPROM fields do NOT prove host-visible EEPROM data.
local M={}

local KEYS={
    "hostname","lang","timezone","ntp_servers",
    "sfp_vendor","sfp_oui","sfp_partno","sfp_rev",
    "sfp_serial","sfp_date","sfp_vendordata",
}
local SFP_MAP={
    sfp_vendor="vendor_name",
    sfp_oui="vendor_oui",
    sfp_partno="vendor_partno",
    sfp_rev="vendor_rev",
    sfp_serial="serial_no",
    sfp_date="datecode",
    sfp_vendordata="vendor_data",
}

local function clean(value,limit)
    if type(value)~="string" or #value>(limit or 255) or
       value:find("[%z\1-\31\127]") then return nil end
    return value
end

local function ntp_text(v)
    if type(v)=="string" then
        local raw=clean(v,255)
        if not raw then return nil end
        local parts={}
        for word in raw:gmatch("%S+") do
            if #word>128 or #parts>=12 then return nil end
            parts[#parts+1]=word
        end
        return table.concat(parts," ")
    end
    if type(v)~="table" then return nil end
    local parts={}
    for index,word in ipairs(v) do
        if index>12 or not clean(word,128) or
           word=="" or word:find("%s") then return nil end
        parts[#parts+1]=word
    end
    return table.concat(parts," ")
end

local function norm(value,id)
    if id=="ntp_servers" then return ntp_text(value) end
    return clean(value,id=="sfp_vendordata" and 32 or 128)
end

local function status(a,b,id)
    local x=norm(a,id)
    local y=norm(b,id)
    if x==nil or y==nil or x=="" or y=="" then
        return "unverified"
    end
    return x==y and "match" or "mismatch"
end

local function fresh_field(id,value)
    local tag="ordinary"
    if id=="sfp_serial" or id=="sfp_vendordata" or id=="sfp_oui" then
        tag="potential_device_identity"
    end
    return {
        id=id,
        saved_value=norm(value,id),
        configured_value=nil,
        observed_value=nil,
        configured_source="unavailable",
        observed_source="unavailable",
        saved_to_configured="unverified",
        configured_to_observed="unverified",
        saved_to_observed="unverified",
        runtime_effect_proven=false,
        persists_across_reboot_proven=false,
        recovery_proven=false,
        hardware_qualified=false,
        sensitivity=tag,
        notes={},
    }
end

local function set_config(field,value,source)
    local parsed=norm(value,field.id)
    if parsed==nil then
        field.notes[#field.notes+1]="configured_value_unavailable"
        return
    end
    field.configured_value=parsed
    field.configured_source=source
    field.saved_to_configured=status(field.saved_value,parsed,field.id)
end

local function set_observed(field,value,source)
    local parsed=norm(value,field.id)
    if parsed==nil or parsed=="" then
        field.notes[#field.notes+1]="independent_runtime_value_unavailable"
        return
    end
    field.observed_value=parsed
    field.observed_source=source
    field.configured_to_observed=status(field.configured_value,parsed,field.id)
    field.saved_to_observed=status(field.saved_value,parsed,field.id)
    field.runtime_effect_proven=true
end

function M.inspect(saved,configured,runtime)
    if type(saved)~="table" or type(configured)~="table" or
       type(runtime)~="table" then
        return nil,"invalid_readonly_device_inputs"
    end
    local fields={}
    for _,id in ipairs(KEYS) do fields[id]=fresh_field(id,saved[id]) end

    set_config(fields.hostname,configured.hostname,"uci_system_hostname")
    set_config(fields.lang,configured.lang,"uci_luci_language")
    set_config(fields.timezone,configured.timezone,"uci_system_zonename")
    set_config(fields.ntp_servers,configured.ntp_servers,"uci_system_ntp_server_list")
    for key,option in pairs(SFP_MAP) do
        set_config(fields[key],(configured.sfp_eeprom or {})[option],
                   "uci_virtual_sfp_eeprom")
        fields[key].notes[#fields[key].notes+1]=
            "virtual_eeprom_configuration_not_host_readback"
    end
    local actual_hostname=clean(runtime.hostname,128)
    if actual_hostname and actual_hostname:match("^[A-Za-z0-9][A-Za-z0-9%._%-]*$") then
        set_observed(fields.hostname,actual_hostname,"kernel_proc_hostname")
    else
        fields.hostname.notes[#fields.hostname.notes+1]=
            "kernel_hostname_unavailable"
    end
    fields.lang.notes[#fields.lang.notes+1]=
        "luci_config_not_active_session_language_proof"
    fields.timezone.notes[#fields.timezone.notes+1]=
        "uci_zonename_not_active_localtime_proof"
    fields.ntp_servers.notes[#fields.ntp_servers.notes+1]=
        "configured_servers_do_not_prove_ntp_sync"
    local summary={observed_runtime=0,configured_only=0,unverified=0,
                   saved_matches_runtime=0,saved_drift_from_runtime=0}
    for _,id in ipairs(KEYS) do
        local f=fields[id]
        if f.runtime_effect_proven then
            summary.observed_runtime=summary.observed_runtime+1
            if f.saved_to_observed=="match" then
                summary.saved_matches_runtime=summary.saved_matches_runtime+1
            elseif f.saved_to_observed=="mismatch" then
                summary.saved_drift_from_runtime=summary.saved_drift_from_runtime+1
            end
        elseif f.configured_value~=nil then
            summary.configured_only=summary.configured_only+1
        else
            summary.unverified=summary.unverified+1
        end
    end
    return {
        schema=1,source="read_only_device_and_virtual_sfp",
        group="device_and_host_visible_sfp",
        no_device_write=true,no_reboot=true,
        no_firmware_commits=true,
        source_only_not_hardware_qualified=true,
        fields=fields,summary=summary,
    }
end

M.fields=KEYS
M.sfp_options=SFP_MAP
return M
