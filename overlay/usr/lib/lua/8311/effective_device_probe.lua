-- AoTT C-011 source-only: bounded read-only device / virtual SFP probes.
-- Fixed key lists. Never read PON registration or account credentials.
-- No input from the browser reaches a shell, UCI setter or filesystem path.
local M={}
local model=require "8311.effective_device_state"
local SYSTEM_FIELDS={"hostname","timezone"}
local UCI_SFP=model.sfp_options

local function strip(value,maxlen)
    if type(value)~="string" or #value>(maxlen or 255)+2 then return nil end
    value=value:gsub("[\r\n]+$","")
    if #value>(maxlen or 255) or value:find("[%z\1-\31\127]") then
        return nil
    end
    return value
end

function M.capture(adapter)
    if type(adapter)~="table" or
       type(adapter.environment)~="function" or
       type(adapter.system_config)~="function" or
       type(adapter.luci_language)~="function" or
       type(adapter.ntp_list)~="function" or
       type(adapter.sfp_option)~="function" or
       type(adapter.kernel_hostname)~="function" then
        return nil,"invalid_readonly_device_adapter"
    end
    local function safe(fn,...)
        local good,value=pcall(fn,...)
        if not good then return nil end
        return value
    end
    local saved={}
    for _,id in ipairs(model.fields) do
        saved[id]=strip(safe(adapter.environment,id),255)
    end
    local configured={sfp_eeprom={}}
    for _,id in ipairs(SYSTEM_FIELDS) do
        configured[id]=strip(safe(adapter.system_config,id),128)
    end
    configured.lang=strip(safe(adapter.luci_language),128)
    local servers=safe(adapter.ntp_list)
    if type(servers)=="table" then
        local all={}
        if #servers<=12 then
            for index,value in ipairs(servers) do
                if type(value)~="string" or #value>128 or
                   value=="" or value:find("%s") then
                    all=nil
                    break
                end
                all[index]=value
            end
        else
            all=nil
        end
        configured.ntp_servers=all
    elseif type(servers)=="string" then
        configured.ntp_servers=strip(servers,255)
    end
    for id,option in pairs(UCI_SFP) do
        configured.sfp_eeprom[option]=strip(
            safe(adapter.sfp_option,option),128)
    end
    local host=strip(safe(adapter.kernel_hostname),128)
    return model.inspect(saved,configured,{hostname=host})
end

-- A source-only implementation. Do not call as an unauthenticated route.
-- The caller must inherit LuCI administrator authentication.
function M.live_device()
    local ok,snapshot=pcall(function()
        local fs=require "nixio.fs"
        local web=require "8311.webutil"
        local uci=require("luci.model.uci").cursor()

        local function bounded(argv,limit)
            local code,result,overflow=web.capture(argv,limit or 256)
            if code==0 and not overflow and type(result)=="string" then
                return result
            end
        end
        local system_keys={hostname=true,timezone=true}
        local allowed={}
        for _,option in pairs(UCI_SFP) do allowed[option]=true end
        local allowed_environment={}
        for _,id in ipairs(model.fields) do allowed_environment[id]=true end

        local adapter={
            environment=function(id)
                if not allowed_environment[id] then return nil end
                return bounded({"/usr/bin/timeout","-k","1","3",
                    "/usr/sbin/fwenv_get","--8311",id},300)
            end,
            system_config=function(key)
                if not system_keys[key] then return nil end
                return uci:get_first("system","system",
                                    key=="timezone" and "zonename" or key)
            end,
            luci_language=function()
                return uci:get("luci","main","lang")
            end,
            ntp_list=function()
                return uci:get_list("system","ntp","server")
            end,
            sfp_option=function(key)
                if not allowed[key] then return nil end
                return uci:get("sfp_eeprom","default",key)
            end,
            kernel_hostname=function()
                return fs.readfile("/proc/sys/kernel/hostname",128)
            end
        }
        return M.capture(adapter)
    end)
    if not ok or type(snapshot)~="table" or snapshot.schema~=1 then
        return nil,"read_only_device_probe_unavailable"
    end
    return snapshot
end

return M
