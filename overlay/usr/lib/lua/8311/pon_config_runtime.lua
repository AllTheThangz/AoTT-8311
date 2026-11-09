-- AoTT-8311 V3 redacted local-consumer verifier for PON/OMCI changes.
local fs=require "nixio.fs"
local web=require "8311.webutil"
local json=require "luci.jsonc"
local uci_lib=require "luci.model.uci"
local pon_uci=require "8311.pon_config_uci"
local pon_mib=require "8311.pon_mib_runtime"
local M={}
local HOSTFILE="/tmp/8311-iphost-hostname"
local DOMAINFILE="/tmp/8311-iphost-domainname"

local function value(records,id)
    local row=records[id]
    return row and row.state=="value" and row.value or nil
end

local function private_text(path,expected)
    local st=fs.lstat(path)
    if expected==nil or expected=="" then
        return st==nil
    end
    if not st or st.type~="reg" or st.uid~=0 or st.nlink~=1 or
       type(st.size)~="number" or st.size>#expected+2 then return false end
    local raw=fs.readfile(path,#expected+3)
    if type(raw)~="string" then return false end
    raw=raw:gsub("[\r\n]+$","")
    return raw==expected
end

local function pon_state()
    local code,out,overflow=web.capture({
        "/usr/bin/timeout","-k","1","4","/usr/bin/pon","psg"
    },1024)
    if code~=0 or overflow or type(out)~="string" then return nil end
    local current=out:match("^current=(%d+)%s") or
        out:match("%scurrent=(%d+)%s") or out:match("current=(%d+)")
    return tonumber(current)
end

local function omcid()
    local code,pids,overflow=web.capture({"/bin/pidof","omcid"},512)
    if code~=0 or overflow or type(pids)~="string" then return false end
    for pid in pids:gmatch("%d+") do
        local raw=fs.readfile("/proc/"..pid.."/cmdline",8192)
        if type(raw)=="string" and raw:find("^/usr/bin/omcid%z") then return true end
    end
    return false
end

local function uboot_reporting(records)
    local code,out,overflow=web.capture({"/sbin/uboot_img_vars.sh","get_uboot_vars"},4096)
    if code~=0 or overflow or type(out)~="string" then
        return nil,"pon_reporting_consumer_unavailable"
    end
    local ok,record=pcall(json.parse,out)
    if not ok or type(record)~="table" then return nil,"pon_reporting_consumer_invalid" end
    local checks={
        sw_verA={"img_versionA"},sw_verB={"img_versionB"},
        override_active={"active_bank"},override_commit={"commit_bank"},
    }
    local verified={}
    for id,map in pairs(checks) do
        local expected=value(records,id)
        if expected~=nil and expected~="" then
            if tostring(record[map[1]] or "")~=expected then
                return nil,"pon_reporting_readback_mismatch_"..id
            end
            verified[id]=true
        else
            -- Unset overrides intentionally delegate to the bootloader/native
            -- value. A nonempty native value is therefore not a mismatch.
            verified[id]=false
        end
    end
    return verified
end

local function event_consumer()
    local st=fs.lstat("/sbin/secure_upgrade.sh")
    if not st or st.type~="reg" or st.uid~=0 or st.nlink~=1 or st.size<1 then
        return false
    end
    return true
end

function M.apply_aux(records)
    for _,entry in ipairs({
        {HOSTFILE,value(records,"iphost_hostname")},
        {DOMAINFILE,value(records,"iphost_domain")},
    }) do
        local path,v=entry[1],entry[2]
        if v==nil or v=="" then
            local st=fs.lstat(path)
            if st and (st.type~="reg" or st.uid~=0 or st.nlink~=1 or fs.unlink(path)~=true) then
                return nil,"pon_iphost_aux_clear_failed"
            end
        else
            if #v>25 or v:find("[%z\1-\31\127]") then return nil,"pon_iphost_aux_invalid" end
            local ok,why=require("8311.webutil").write(path,v.."\n",600)
            if not ok then return nil,why or "pon_iphost_aux_write_failed" end
        end
    end
    return true
end

function M.local_verify(records)
    local uci,why=pon_uci.verify(records)
    if not uci then return nil,why end
    local mib,mwhy=pon_mib.verify(records)
    if not mib then return nil,mwhy end
    if not private_text(HOSTFILE,value(records,"iphost_hostname")) then
        return nil,"pon_iphost_hostname_readback_mismatch"
    end
    if not private_text(DOMAINFILE,value(records,"iphost_domain")) then
        return nil,"pon_iphost_domain_readback_mismatch"
    end
    local reporting,rwhy=uboot_reporting(records)
    if not reporting then return nil,rwhy end
    if not event_consumer() then return nil,"pon_firmware_match_consumer_unavailable" end
    if pon_state()~=51 then return nil,"pon_not_registered_o5_1" end
    if not omcid() then return nil,"omcid_not_running" end
    return {
        schema=1,status="PON_LOCAL_CONSUMERS_VERIFIED",
        pon_registered_o5_1=true,omcid_running=true,
        local_uci_verified=true,mib_local_verified=true,
        reporting_consumer_verified=true,
        firmware_match_consumer_available=true,
        iphost_aux_verified=true,
        olt_per_field_effect_proven=false,
        subscriber_values_returned=false,
        contains_configuration_values=false,
    }
end

function M.pon_state()
    return pon_state()
end

function M.omcid_running()
    return omcid()
end

return M
