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

local function timezone_text(value)
    local text=clean(value,128)
    return text and text:gsub("_"," ") or nil
end

local function ntp_equal(a,b)
    local left,right=ntp_text(a),ntp_text(b)
    if left==nil or right==nil then return nil end
    local counts={}
    for word in left:gmatch("%S+") do counts[word]=(counts[word] or 0)+1 end
    for word in right:gmatch("%S+") do
        if not counts[word] or counts[word]<1 then return false end
        counts[word]=counts[word]-1
    end
    for _,count in pairs(counts) do if count~=0 then return false end end
    return true
end

local function ntp_contains(expected,actual)
    local left,right=ntp_text(expected),ntp_text(actual)
    if left==nil or right==nil then return nil end
    local counts={}
    for word in right:gmatch("%S+") do counts[word]=(counts[word] or 0)+1 end
    for word in left:gmatch("%S+") do
        if not counts[word] or counts[word]<1 then return false end
        counts[word]=counts[word]-1
    end
    return true
end

local function norm(value,id)
    if id=="ntp_servers" then return ntp_text(value) end
    if id=="timezone" then return timezone_text(value) end
    return clean(value,id=="sfp_vendordata" and 32 or 128)
end

local function status(a,b,id)
    local x=norm(a,id)
    local y=norm(b,id)
    if x==nil or y==nil then return "unverified" end
    if id=="ntp_servers" then
        local same=ntp_equal(x,y)
        return same==nil and "unverified" or same and "match" or "mismatch"
    end
    if id=="lang" and (x=="auto" or y=="auto") then return "unverified" end
    if x=="" or y=="" then return "unverified" end
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

local function set_observed(field,value,source,allow_empty)
    local parsed=norm(value,field.id)
    if parsed==nil or (parsed=="" and not allow_empty) then
        field.notes[#field.notes+1]="independent_runtime_value_unavailable"
        return
    end
    field.observed_value=parsed
    field.observed_source=source
    if field.id=="ntp_servers" then
        local configured=ntp_contains(field.configured_value,parsed)
        local saved=ntp_contains(field.saved_value,parsed)
        field.configured_to_observed=configured==nil and "unverified" or
            configured and "match" or "mismatch"
        field.saved_to_observed=saved==nil and "unverified" or
            saved and "match" or "mismatch"
    else
        field.configured_to_observed=status(field.configured_value,parsed,field.id)
        field.saved_to_observed=status(field.saved_value,parsed,field.id)
    end
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

    local active_language=clean(runtime.lang,128)
    if active_language and active_language~="" then
        set_observed(fields.lang,active_language,"active_luci_request_language")
        fields.lang.notes[#fields.lang.notes+1]=
            "active_language_is_this_authenticated_request"
    else
        fields.lang.notes[#fields.lang.notes+1]=
            "active_luci_request_language_unavailable"
    end

    local active_timezone=timezone_text(runtime.timezone)
    if active_timezone and active_timezone~="" then
        set_observed(fields.timezone,active_timezone,
                     "tmp_localtime_zoneinfo_target")
    else
        fields.timezone.notes[#fields.timezone.notes+1]=
            "active_localtime_zone_unavailable"
    end

    local ntp=runtime.ntp
    if type(ntp)=="table" and ntp.probe_ok==true and
       type(ntp.running)=="boolean" then
        if ntp.running then
            local peers=ntp_text(ntp.peers)
            if peers~=nil then
                set_observed(fields.ntp_servers,peers,
                             "active_ntpd_process_arguments",true)
                fields.ntp_servers.notes[#fields.ntp_servers.notes+1]=
                    "active_ntpd_peers_do_not_prove_clock_synchronization"
            else
                fields.ntp_servers.notes[#fields.ntp_servers.notes+1]=
                    "active_ntpd_peer_parse_failed"
            end
        else
            set_observed(fields.ntp_servers,"","ntpd_process_absent",true)
            fields.ntp_servers.notes[#fields.ntp_servers.notes+1]=
                "ntpd_absence_verifies_disabled_runtime_only"
        end
    else
        fields.ntp_servers.notes[#fields.ntp_servers.notes+1]=
            "active_ntpd_process_probe_unavailable"
    end
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
