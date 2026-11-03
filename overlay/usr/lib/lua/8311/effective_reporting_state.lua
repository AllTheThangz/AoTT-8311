-- C-011: ten noncredential OMCI reported-field readback, presence only.
-- No raw identity/version/regex/bootloader text is returned to the UI.
-- Source validation is NOT confirmation of OMCI MIB effect or OLT support.
local M={}
local FIELDS={
    "equipment_id","hw_ver","cp_hw_ver_sync","sw_verA","sw_verB",
    "fw_match_b64","fw_match_num","override_active","override_commit",
    "pon_slot",
}
local FIELD_SET={}
for _,id in ipairs(FIELDS) do FIELD_SET[id]=true end

local function printable(v,limit,allow_empty)
    if type(v)~="string" or #v>limit or
       v:find("[%z\1-\31\127]") or
       (not allow_empty and #v==0) then
        return false
    end
    return true
end
local function decimal(v,min,max)
    if type(v)~="string" or not v:match("^%d+$") or #v>5 then
        return false
    end
    local n=tonumber(v)
    return n and n>=min and n<=max and tostring(n)==v
end
local function base64(v)
    if not printable(v,255,false) or #v%4~=0 then return false end
    local body,tail=v:match("^([A-Za-z0-9+/]*)(=*)$")
    if not body or not tail or #tail>2 then return false end
    return #body>0 and
        ((#tail==0 and #body%4==0) or
         (#tail==1 and #body%4==3) or
         (#tail==2 and #body%4==2))
end
local function valid(id,v)
    if v==nil or type(v)~="string" then return false end
    if id=="equipment_id" then return printable(v,20,false) end
    if id=="hw_ver" or id=="sw_verA" or id=="sw_verB" then
        return printable(v,14,false)
    end
    if id=="cp_hw_ver_sync" then return v=="0" or v=="1" end
    if id=="fw_match_b64" then return base64(v) end
    if id=="fw_match_num" then return decimal(v,1,99) end
    if id=="override_active" or id=="override_commit" then
        return v=="A" or v=="B"
    end
    if id=="pon_slot" then return decimal(v,1,254) end
    return false
end

function M.inspect(saved,images)
    if type(saved)~="table" or type(images)~="table" then
        return nil,"invalid_reporting_inputs"
    end
    local rows={}
    local summary={source_fields=10,source_present=0,
        source_format_valid=0,source_format_invalid=0,
        source_unavailable=0,image_labels_compared=0,
        image_labels_matching=0,reporting_runtime_effects_verified=0,
        hardware_qualified=0}
    for _,id in ipairs(FIELDS) do
        local value=saved[id]
        local presence=type(value)=="string" and #value>0
        local format_status="unavailable"
        if presence then
            format_status=valid(id,value) and "valid_source_format"
                           or "invalid_source_format"
            summary.source_present=summary.source_present+1
            if format_status=="valid_source_format" then
                summary.source_format_valid=summary.source_format_valid+1
            else
                summary.source_format_invalid=summary.source_format_invalid+1
            end
        else
            summary.source_unavailable=summary.source_unavailable+1
        end
        local comparison="unavailable"
        if id=="sw_verA" or id=="sw_verB" then
            local label=images[id=="sw_verA" and "A" or "B"]
            if valid(id,value) and valid(id,label) then
                comparison=value==label and "labels_match"
                                        or "labels_differ"
                summary.image_labels_compared=summary.image_labels_compared+1
                if comparison=="labels_match" then
                    summary.image_labels_matching=
                        summary.image_labels_matching+1
                end
            end
        end
        rows[id]={
            id=id,source_scope="aott_prefixed_boot_environment",
            source_presence=presence,
            source_format=format_status,
            reported_image_to_boot_label=comparison,
            reported_bank_not_actual_boot_selector=true,
            content_redacted=true,
            raw_value_exported=false,
            runtime_effect_proven=false,
            omci_mib_effect_proven=false,
            olt_received_reported_value_proven=false,
            actually_flashes_or_commits_firmware=false,
            survives_reboot_proven=false,
            hardware_qualified=false,
        }
    end
    return {
        schema=1,group="omci_reporting_noncredential",
        source="boot_environment_presence_and_format_only",
        fields=rows,summary=summary,
        no_device_write=true,no_reboot=true,no_firmware_commit=true,
        no_mib_edit=true,
        no_registration_secret_read=true,
        no_subscriber_identity_exported=true,
        no_raw_environment_value_exported=true,
        no_olt_effect_proof=true,
        actual_boot_bank_verified=false,
        proves_subscriber_internet=false,
        source_only_not_hardware_qualified=true,
    }
end
M.fields=FIELDS
M.field_set=FIELD_SET
return M
