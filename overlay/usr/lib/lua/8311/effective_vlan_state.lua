-- AoTT-8311 C-011: pure Lua 5.1, read-only VLAN service evidence.
-- No native I/O, credentials, shell, traffic control writes, or reboots.
-- Last published fixer receipt is historical evidence, never live TC proof.
local M={}
local IDS={"fix_vlans","internet_vlan","services_vlan"}

local function text(v, limit)
    if type(v)~="string" or #v>(limit or 80) or
       v:find("[%z\1-\31\127]") then return nil end
    return v
end

local function uint(v, low, high)
    if not text(v,12) or not v:match("^%d+$") then return nil end
    if #v>1 and v:sub(1,1)=="0" then return nil end
    local num=tonumber(v)
    if not num or num<low or num>high then return nil end
    return tostring(num)
end

local function mode(v)
    return uint(v,0,2)
end

local function internet(v)
    return uint(v,0,4095)
end

local function services(v)
    return uint(v,1,4095)
end

local NORMALIZE={
    fix_vlans=mode,internet_vlan=internet,services_vlan=services,
}

local function match(a,b)
    if a==nil or b==nil then return "unverified" end
    return a==b and "match" or "mismatch"
end

-- Parse only safe fixed scalar keys from a private root-owned native
-- reconcile receipt. This is data, NOT executable shell. NEVER source it.
function M.parse_last_reconciliation(body)
    if type(body)~="string" or #body>4096 or
       body:find("[%z\1-\8\11\12\14-\31\127]") then
        return nil,"invalid_native_receipt"
    end
    local keys={
        INTERNET_VLAN=true,SERVICES_VLAN=true,STATE_HASH=true,
    }
    local found={}
    for line in (body.."\n"):gmatch("(.-)\n") do
        local key,value=line:match("^([A-Z_]+)=(.*)$")
        if key and keys[key] then
            if found[key]~=nil then
                return nil,"duplicate_native_receipt_key"
            end
            if not value or #value>80 or
               not value:match("^[A-Za-z0-9]+$") then
                return nil,"invalid_native_receipt_value"
            end
            found[key]=value
        end
    end
    if not found.INTERNET_VLAN or not found.SERVICES_VLAN or
       not found.STATE_HASH then
        return nil,"incomplete_native_receipt"
    end
    local local_internet=internet(found.INTERNET_VLAN)
    local local_services=services(found.SERVICES_VLAN)
    local hash=found.STATE_HASH
    if not local_internet or not local_services or
       #hash~=64 or not hash:match("^[0-9a-f]+$") or
       local_internet==local_services then
        return nil,"invalid_native_receipt_values"
    end
    return {
        internet_vlan=local_internet,
        services_vlan=local_services,
        topology_hash=hash,
    }
end

local function valid_hash(v)
    return type(v)=="string" and #v==64 and
           v:match("^[0-9a-f]+$")~=nil
end

function M.inspect(saved, last_body, current_hash, daemon)
    if type(saved)~="table" then
        return nil,"invalid_vlan_source"
    end
    if daemon~=nil and type(daemon)~="boolean" then
        return nil,"invalid_daemon_status"
    end

    local last,reason=M.parse_last_reconciliation(last_body)
    local unchanged=nil
    if last and valid_hash(current_hash) then
        unchanged=(last.topology_hash==current_hash)
    end
    local summary={
        saved_fields_valid=0,invalid_saved_fields=0,
        recorded_fields=0,saved_match_recorded=0,
        saved_drift_from_recorded=0,
        live_tc_rules_verified=0
    }
    local fields={}
    for _,id in ipairs(IDS) do
        local raw=saved[id]
        local normalized=raw~=nil and NORMALIZE[id](raw) or nil
        local notes={}
        local recorded=last and last[id] or nil
        if id=="fix_vlans" then
            notes[#notes+1]="source_default_mode_1_if_unset"
            notes[#notes+1]="process_presence_not_proof_of_service_mapping"
        elseif id=="internet_vlan" then
            notes[#notes+1]="source_default_internet_vlan_0_if_unset"
        else
            notes[#notes+1]="unset_services_vlan_requires_provider_detection"
        end
        if raw~=nil and not normalized then
            notes[#notes+1]="invalid_saved_value"
            summary.invalid_saved_fields=summary.invalid_saved_fields+1
        elseif normalized then
            summary.saved_fields_valid=summary.saved_fields_valid+1
        end
        if id=="fix_vlans" then
            recorded=nil -- No mode is certified by a TC rules snapshot.
        end
        local compared=match(normalized,recorded)
        if recorded then
            summary.recorded_fields=summary.recorded_fields+1
        end
        if compared=="match" then
            summary.saved_match_recorded=summary.saved_match_recorded+1
        elseif compared=="mismatch" then
            summary.saved_drift_from_recorded=
                summary.saved_drift_from_recorded+1
        end
        if last and (id=="internet_vlan" or id=="services_vlan") then
            notes[#notes+1]="last_native_reconcile_receipt_not_current_TC_proof"
        end
        fields[id]={
            id=id,
            saved_value=normalized,
            source_default=(id=="fix_vlans" and "1"
                            or id=="internet_vlan" and "0" or nil),
            last_recorded_value=recorded,
            saved_to_last_recorded=compared,
            last_recorded_source=recorded and
                "root_owned_native_reconciliation_receipt" or "unavailable",
            observed_effective_value=nil,
            runtime_effect_proven=false,
            reboot_persistence_proven=false,
            recovery_proven=false,
            hardware_qualified=false,
            notes=notes
        }
    end
    return {
        schema=1,
        group="isp_vlan",
        source="source_only_readonly_service_mapping",
        no_device_write=true,no_reboot=true,
        no_firmware_commit=true,
        contains_registration_secret=false,
        source_only_not_hardware_qualified=true,
        fields=fields,
        daemon={
            running=daemon,
            source="pidof_read_only",
            proves_translation_active=false
        },
        last_reconciliation={
            present=last~=nil,
            interpretation=last and "historical_native_receipt" or
                           "receipt_not_validated",
            absent_reason=last and nil or reason,
            topology_matches_record=unchanged,
            topology_match_proves_rules_current=false,
            current_traffic_control_rules_verified=false,
        },
        summary=summary,
        internet_path_verified=false
    }
end
M.fields=IDS
return M
