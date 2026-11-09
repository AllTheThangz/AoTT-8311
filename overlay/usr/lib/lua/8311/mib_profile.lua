-- AoTT-8311 V3 read-only OMCI MIB profile introspection.
-- Parses only root-owned /etc/mibs/*.ini profiles. No writes, shell execution,
-- subscriber identifiers, or OLT traffic are involved.
local fs=require "nixio.fs"
local M={}
local MAX=131072
local MAX_LINES=4096
local MAX_LINE=8192

local function safe_path(path)
    return type(path)=="string" and
        path:match("^/etc/mibs/[A-Za-z0-9_.-]+%.ini$")~=nil
end

local function tokenize(line)
    local tokens,i,n={},1,#line
    while i<=n do
        while i<=n and line:sub(i,i):match("%s") do i=i+1 end
        if i>n or line:sub(i,i)=="#" then break end
        local start=i
        if line:sub(i,i)=='"' then
            i=i+1
            local closed=false
            while i<=n do
                local c=line:sub(i,i)
                if c=="\\" then
                    if i==n then return nil,"mib_escape_truncated" end
                    i=i+2
                elseif c=='"' then
                    i=i+1;closed=true;break
                else
                    i=i+1
                end
            end
            if not closed then return nil,"mib_quote_unterminated" end
        else
            while i<=n and not line:sub(i,i):match("%s") do
                if line:sub(i,i)=="#" then break end
                i=i+1
            end
        end
        tokens[#tokens+1]=line:sub(start,i-1)
        if #tokens>160 then return nil,"mib_record_too_wide" end
    end
    return tokens
end

local function clean_token(value)
    if type(value)~="string" then return nil end
    if value:sub(1,1)=='"' and value:sub(-1)=='"' and #value>=2 then
        value=value:sub(2,-2)
        value=value:gsub("\\s"," "):gsub("\\0","")
        value=value:gsub('\\"','"'):gsub("\\\\","\\")
    end
    value=value:gsub("^%s+",""):gsub("%s+$","")
    if #value>128 or value:find("[%z\1-\31\127]") then return nil end
    return value
end

local function array_from_set(set,numeric)
    local out={}
    for value in pairs(set) do out[#out+1]=value end
    table.sort(out,numeric and function(a,b)return a<b end or nil)
    return out
end

local function uniform_attr(records,class_id,param)
    local found=nil
    local seen=false
    for _,row in ipairs(records) do
        if row.class_id==class_id then
            local value=row.tokens[row.me_index+param+1]
            if value~=nil then
                value=clean_token(value)
                if value==nil then return nil,false end
                if not seen then found=value;seen=true
                elseif found~=value then return nil,false end
            end
        end
    end
    return found,seen
end

local function inspect_data(path,data)
    if type(data)~="string" or #data<1 or #data>MAX or data:find("%z") then
        return nil,"mib_profile_content_invalid"
    end
    local records,counts={},{}
    local conditional,bang=0,0
    local uni_set,slot_set={},{}
    local lines=0
    for raw in (data.."\n"):gmatch("(.-)\n") do
        lines=lines+1
        if lines>MAX_LINES or #raw>MAX_LINE then
            return nil,"mib_profile_structure_too_large"
        end
        local stripped=raw:match("^%s*(.-)%s*$") or ""
        if stripped~="" and stripped:sub(1,1)~="#" then
            local tokens,why=tokenize(raw)
            if not tokens then return nil,why end
            if #tokens>0 then
                local marker=nil
                local mi=1
                if tokens[1]=="?" or tokens[1]=="!" then
                    marker=tokens[1];mi=2
                    if marker=="?" then conditional=conditional+1 else bang=bang+1 end
                end
                local class_id=tonumber(tokens[mi])
                if not class_id or class_id<0 or class_id>65535 or
                   not tokens[mi+1] then
                    return nil,"mib_profile_record_invalid"
                end
                counts[class_id]=(counts[class_id] or 0)+1
                records[#records+1]={
                    marker=marker,class_id=class_id,
                    instance=tokens[mi+1],tokens=tokens,me_index=mi,
                }
                -- Mirror the vendor-profile UNI relationship convention used
                -- by the guarded slot editor. Priority Queue ME 277 attribute
                -- 6 contains related-port encodings 0xSSUUxxxx for physical
                -- UNI queues. Only 0x00xx queue instances participate.
                if class_id==277 then
                    local qinst=(tokens[mi+1] or ""):lower()
                    local port=(tokens[mi+7] or ""):lower()
                    local ss,uu=port:match("^0x(%x%x)(%x%x)%x%x%x%x$")
                    local slot=ss and tonumber(ss,16) or nil
                    local uni=uu and tonumber(uu,16) or nil
                    if qinst:match("^0x00%x%x$") and slot and
                       slot>=1 and slot<=254 and uni and uni>=1 and uni<=254 then
                        slot_set[slot]=true;uni_set[uni]=true
                    end
                end
            end
        end
    end
    local unis=array_from_set(uni_set,true)
    local slots=array_from_set(slot_set,true)
    local slot_editable=#unis==1 and unis[1]==1 and #slots==1
    local slot_reason
    if slot_editable then slot_reason="single_uni_slot_mapping"
    elseif #unis>1 then slot_reason="multiple_physical_unis"
    elseif #unis==0 and (counts[329] or 0)>0 then
        slot_reason="veip_profile_no_physical_uni_slot_mapping"
    elseif #unis==0 then slot_reason="physical_uni_slot_not_inferred"
    else slot_reason="unsupported_uni_slot_topology" end

    local vendor6,vendor6ok=uniform_attr(records,6,5)
    local vendor256,vendor256ok=uniform_attr(records,256,1)
    local hw,hwok=uniform_attr(records,256,2)
    local cp_hw,cpok=uniform_attr(records,6,4)
    local equipment,equipok=uniform_attr(records,257,1)
    local vendor_default=nil
    if vendor6ok and vendor256ok and vendor6==vendor256 then vendor_default=vendor6 end

    local filename=path:match("([^/]+)$")
    local variant="generic"
    if filename:find("telus",1,true) then variant="telus"
    elseif filename:find("bell",1,true) then variant="bell"
    elseif filename:find("voip",1,true) then variant="voip"
    elseif filename:find("32tcont",1,true) then variant="32tcont" end

    local profile_kind="other"
    local veip=(counts[329] or 0)>0
    if #unis>1 and veip then profile_kind="multi_uni_plus_veip"
    elseif #unis>1 then profile_kind="multi_uni"
    elseif #unis==1 and veip then profile_kind="single_uni_plus_veip"
    elseif #unis==1 then profile_kind="single_uni"
    elseif veip then profile_kind="veip" end

    local applicability={
        vendor_id=(counts[6] or 0)>0 and (counts[256] or 0)>0,
        hw_ver=(counts[256] or 0)>0,
        cp_hw_ver_sync=(counts[6] or 0)>0,
        equipment_id=(counts[257] or 0)>0,
        software_reporting=(counts[7] or 0)>0,
        iphost_identity=(counts[134] or 0)>0,
        pon_slot=slot_editable,
    }
    local defaults={
        vendor_id=vendor_default,
        hw_ver=hwok and hw or nil,
        cp_hw_ver=cpok and cp_hw or nil,
        equipment_id=equipok and equipment or nil,
        pon_slot=slot_editable and tostring(slots[1]) or nil,
    }

    local notes={}
    if #unis>1 then
        notes[#notes+1]="Multiple physical UNI relationships detected; a single global UNI-slot override is unsafe and is disabled."
    elseif not slot_editable then
        notes[#notes+1]="No safely editable physical UNI-1 slot mapping was inferred; use the profile-native slot topology."
    end
    if not applicability.iphost_identity then
        notes[#notes+1]="IP Host Config Data ME 134 is absent; IP-host identity overrides are not applicable to this profile."
    end
    if (counts[329] or 0)>0 then
        notes[#notes+1]="VEIP ME 329 is present; this profile uses virtual-Ethernet topology in addition to or instead of physical UNI mapping."
    end
    if variant~="generic" then
        notes[#notes+1]="Filename identifies this as the "..variant.." profile variant; provider compatibility is not inferred from the filename."
    end

    return {
        schema=1,path=path,filename=filename,variant_hint=variant,
        profile_kind=profile_kind,conditional_records=conditional,
        bang_records=bang,record_count=#records,
        topology={
            physical_uni_count=#unis,physical_uni_numbers=unis,
            slot_candidates=slots,slot_editable=slot_editable,
            slot_reason=slot_reason,
            ethernet_uni_me11_count=counts[11] or 0,
            iphost_me134_count=counts[134] or 0,
            veip_me329_count=counts[329] or 0,
            tcont_me262_count=counts[262] or 0,
            priority_queue_me277_count=counts[277] or 0,
            traffic_scheduler_me278_count=counts[278] or 0,
            vendor_extension_me443_count=counts[443] or 0,
            me53_count=counts[53] or 0,
        },
        applicability=applicability,defaults=defaults,notes=notes,
        identity_values_are_profile_defaults=true,
        olt_compatibility_proven=false,hardware_qualified=false,
        contains_subscriber_values=false,no_device_write=true,
    }
end

function M.inspect(path,adapter)
    if not safe_path(path) then return nil,"mib_profile_path_invalid" end
    local A=adapter or fs
    if type(A)~="table" or type(A.lstat)~="function" or
       type(A.readfile)~="function" then return nil,"mib_profile_adapter_invalid" end
    local st=A.lstat(path)
    if not st or st.type~="reg" or st.uid~=0 or st.gid~=0 or
       st.nlink~=1 or type(st.size)~="number" or st.size<1 or st.size>MAX then
        return nil,"mib_profile_file_unavailable"
    end
    local data=A.readfile(path,MAX+1)
    if type(data)~="string" or #data~=st.size then
        return nil,"mib_profile_read_failed"
    end
    return inspect_data(path,data)
end

function M.validate_for_configuration(profile,proposed,changed)
    if type(profile)~="table" or profile.schema~=1 or
       type(proposed)~="table" or type(changed)~="table" then
        return nil,{mib_file="MIB capability inspection is unavailable"}
    end
    local errors={}
    local app=profile.applicability or {}
    if not app.pon_slot and proposed.pon_slot and proposed.pon_slot~="" and
       (changed.pon_slot or changed.mib_file or changed.__pon_transaction) then
        errors.pon_slot="This MIB does not support a safe single-UNI slot override. Clear the slot override in the same reviewed change to use the profile-native topology."
    end
    if changed.iphost_mac or changed.iphost_hostname or changed.iphost_domain then
        if not app.iphost_identity then
            local msg="The selected MIB does not contain IP Host Config Data ME 134, so IP-host identity overrides are not applicable."
            if changed.iphost_mac then errors.iphost_mac=msg end
            if changed.iphost_hostname then errors.iphost_hostname=msg end
            if changed.iphost_domain then errors.iphost_domain=msg end
        end
    end
    if changed.cp_hw_ver_sync and proposed.cp_hw_ver_sync=="1" and
       not app.cp_hw_ver_sync then
        errors.cp_hw_ver_sync="The selected MIB has no Circuit Pack ME 6 records to synchronize."
    end
    if changed.vendor_id and not app.vendor_id then
        errors.vendor_id="The selected MIB does not contain both vendor-ID target MEs required for a safe override."
    end
    if changed.hw_ver and not app.hw_ver then
        errors.hw_ver="The selected MIB does not contain ONU-G hardware-version storage required for this override."
    end
    if changed.equipment_id and not app.equipment_id then
        errors.equipment_id="The selected MIB does not contain ONU2-G equipment-ID storage required for this override."
    end
    if not app.software_reporting then
        local msg="The selected MIB has no Software Image ME 7 records for reported image metadata."
        if changed.sw_verA then errors.sw_verA=msg end
        if changed.sw_verB then errors.sw_verB=msg end
        if changed.override_active then errors.override_active=msg end
        if changed.override_commit then errors.override_commit=msg end
    end
    if next(errors) then return nil,errors end
    return true
end

M.safe_path=safe_path
M.inspect_data=inspect_data
return M
