-- AoTT-8311 C-011: pure Lua 5.1 read-only PON/OMCI state comparison.
-- Four noncredential GUI settings only. No live writes, I/O or secrets.
-- UCI config, MIB filename existence and PON O5.1 do NOT prove an OMCI
-- runtime consumer applied any one saved setting or Internet service works.
local M={}
local IDS={"pon_mode","omcc_version","iop_mask","mib_file"}
local function trim(v,max)
    if type(v)~="string" or #v>(max or 128) then return nil end
    v=v:match("^%s*(.-)%s*$")
    if v:find("[%z\1-\31\127]") or #v>(max or 128) then return nil end
    return v
end

local function normalize_mode(value)
    value=trim(value,24)
    if not value then return nil end
    local s=value:lower():gsub("%-","")
    return (s=="xgspon" or s=="xgpon") and s or nil
end

local function normalize_omcc(value)
    value=trim(value,16)
    if not value then return nil end
    local h=value:match("^0[xX](%x%x)$")
    if not h then return nil end
    local n=tonumber(h,16)
    if not n or n<0x82 or n>0xBF then return nil end
    return string.format("0x%02X",n)
end

local function normalize_iop(value)
    value=trim(value,16)
    if not value or not value:match("^%d+$") then return nil end
    local n=tonumber(value)
    if not n or n<0 or n>127 then return nil end
    return tostring(n)
end

local function normalize_mib(value)
    value=trim(value,128)
    if not value or value=="" then return nil end
    local name=value:match("^/etc/mibs/([A-Za-z0-9_.%-]+%.ini)$")
             or value:match("^([A-Za-z0-9_.%-]+%.ini)$")
    if not name or name=="..ini" or name:find("%.%.") then return nil end
    return "/etc/mibs/"..name
end

local NORMALIZE={
    pon_mode=normalize_mode,omcc_version=normalize_omcc,
    iop_mask=normalize_iop,mib_file=normalize_mib,
}
local function comparison(a,b)
    if not a or not b then return "unverified" end
    return a==b and "match" or "mismatch"
end

function M.parse_pon_status(raw)
    if type(raw)~="string" or #raw>1024 or
       raw:find("[%z\1-\8\11\12\14-\31\127]") then
        return nil,"pon_status_unavailable"
    end
    local one=nil
    local count=0
    -- Whole whitespace-delimited key only. Do not accept "notcurrent",
    -- and reject multiple state entries instead of choosing the first.
    for token in raw:gmatch("%S+") do
        if token=[REDACTED] then
            local code=token=[REDACTED]
            if not code then return nil,"invalid_pon_state" end
            count=count+1
            if count>1 then return nil,"ambiguous_pon_state" end
            one=code
        end
    end
    if count~=1 or not one or #one>3 then
        return nil,"pon_status_unavailable"
    end
    local value=tonumber(one)
    if not value or value<0 or value>255 then
        return nil,"invalid_pon_state"
    end
    return value,nil
end

function M.inspect(saved,configured,state)
    if type(saved)~="table" or type(configured)~="table" then
        return nil,"invalid_readonly_pon_inputs"
    end
    if state~=nil and
       (type(state)~="number" or state~=math.floor(state)
        or state<0 or state>255) then
        return nil,"invalid_pon_state"
    end
    local fields={}
    local summary={configured=0,saved_match_configured=0,
                   saved_mismatch_configured=0,unavailable=0,
                   independently_effective_verified=0}
    for _,id in ipairs(IDS) do
        local n=NORMALIZE[id]
        local s=n(saved[id])
        local c=n(configured[id])
        local cmp=comparison(s,c)
        local row={
            id=id,
            saved_value=s,
            configured_value=c,
            observed_value=nil,
            configured_source=(c and "uci_vendor_configuration"
                                 or "unavailable"),
            observed_source="unavailable",
            saved_to_configured=cmp,
            configured_to_observed="unverified",
            saved_to_observed="unverified",
            runtime_effect_proven=false,
            persists_across_reboot_proven=false,
            recovery_proven=false,
            hardware_qualified=false,
            notes={"uci_value_not_independent_omci_runtime_proof"},
        }
        if id=="mib_file" then
            row.notes[#row.notes+1]=
                "mib_path_is_configured_not_proof_of_loaded_profile"
        end
        if c then
            summary.configured=summary.configured+1
        else
            summary.unavailable=summary.unavailable+1
        end
        if cmp=="match" then
            summary.saved_match_configured=
                summary.saved_match_configured+1
        elseif cmp=="mismatch" then
            summary.saved_mismatch_configured=
                summary.saved_mismatch_configured+1
        end
        fields[id]=row
    end

    local associated=nil
    if state~=nil then associated=(state==51) end
    local pon={
        state=state,
        label=state==51 and "O5.1 associated"
              or (state and "PON state observed" or "Unknown"),
        association_observed=associated,
        independent_source=state and "native_pon_psg" or "unavailable",
        proves_internet_connectivity=false,
        proves_setting_effect=false,
        o5_is_not_wan_proof=true,
    }
    return {
        schema=1,source="read_only_pon_configuration_and_registration",
        group="pon_omci_noncredential",
        no_device_write=true,no_reboot=true,
        no_firmware_commits=true,
        contains_registration_secret=false,
        source_only_not_hardware_qualified=true,
        fields=fields,registration=pon,summary=summary
    }
end
M.fields=IDS
M.normalize=NORMALIZE
return M
