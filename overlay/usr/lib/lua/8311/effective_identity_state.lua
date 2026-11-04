-- C-011: nine sensitive stored-override readbacks, redacted at the boundary.
-- Format validation is shared with the real save path; no credential values,
-- hashes, lengths, substrings or runtime/OLT authentication claims are returned.
local M={}
local config=require "8311.config"
local FIELDS={"gpon_sn","vendor_id","reg_id_hex","loid","lpwd",
              "iphost_mac","iphost_hostname","iphost_domain","root_pwhash"}
local SPECS={
    gpon_sn={id="gpon_sn",type="text",maxlength=12,pattern=true,required=true},
    vendor_id={id="vendor_id",type="text",maxlength=4,pattern=true},
    reg_id_hex={id="reg_id_hex",type="text",maxlength=72,pattern=true},
    loid={id="loid",type="text",maxlength=24},
    lpwd={id="lpwd",type="text",maxlength=12},
    iphost_mac={id="iphost_mac",type="text",maxlength=17,pattern=true},
    iphost_hostname={id="iphost_hostname",type="text",maxlength=25},
    iphost_domain={id="iphost_domain",type="text",maxlength=25},
    root_pwhash={id="root_pwhash",type="text",maxlength=255,pattern=true},
}

function M.inspect(observations)
    if type(observations)~="table" then return nil,"identity_input_unavailable" end
    local rows={}
    local counts={source_fields=9,valid_saved_override=0,
        invalid_saved_override=0,unset=0,unavailable=0,
        runtime_effects_verified=0,hardware_qualified=0}
    for _,id in ipairs(FIELDS) do
        local record=observations[id]
        local status="unavailable"
        if type(record)=="table" then
            if record.state=="unset" and record.value==nil then
                status="unset"
            elseif record.state=="present" and type(record.value)=="string" and
                   #record.value>0 then
                local ok,why=pcall(config.validate,SPECS[id],record.value)
                status=(ok and why==nil) and "valid_saved_override"
                       or "invalid_saved_override"
            elseif record.state=="invalid" then
                status="invalid_saved_override"
            end
        end
        counts[status]=counts[status]+1
        rows[id]={id=id,source_status=status,content_redacted=true,
            raw_value_exported=false,value_hash_exported=false,
            value_length_exported=false,stored_override_only=true,
            fallback_value_not_resolved=true,runtime_effect_proven=false,
            authentication_success_proven=false,survives_reboot_proven=false,
            hardware_qualified=false}
    end
    return {schema=1,group="sensitive_identity_override",fields=rows,
        summary=counts,no_device_write=true,no_raw_environment_exported=true,
        no_credential_hash_exported=true,no_identity_exported=true,
        no_olt_or_login_authentication_claim=true,
        source_only_not_hardware_qualified=true}
end
function M.limit(id)
    local spec=SPECS[id]
    return spec and spec.maxlength or nil
end
function M.field_ids()
    local copy={}
    for i,id in ipairs(FIELDS) do copy[i]=id end
    return copy
end
return M
