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
       type(adapter.kernel_hostname)~="function" or
       type(adapter.active_language)~="function" or
       type(adapter.active_timezone)~="function" or
       type(adapter.active_ntp)~="function" then
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
    local active_language=strip(safe(adapter.active_language),128)
    local active_timezone=strip(safe(adapter.active_timezone),128)
    local active_ntp=safe(adapter.active_ntp)
    if type(active_ntp)~="table" then active_ntp=nil end
    return model.inspect(saved,configured,{
        hostname=host,lang=active_language,timezone=active_timezone,
        ntp=active_ntp
    })
end

-- A source-only implementation. Do not call as an unauthenticated route.
-- The caller must inherit LuCI administrator authentication.
function M.live_device(request_language)
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
            end,
            active_language=function()
                if type(request_language)=="string" and #request_language<=128 and
                   not request_language:find("[%z\1-\31\127]") then
                    return request_language
                end
            end,
            active_timezone=function()
                local link=fs.readlink("/tmp/localtime")
                local prefix="/usr/share/zoneinfo/"
                if type(link)=="string" and link:sub(1,#prefix)==prefix then
                    return link:sub(#prefix+1):gsub("_"," ")
                end
                local fallback=fs.readfile("/tmp/TZ",128)
                if type(fallback)=="string" then
                    return fallback:gsub("[\r\n]+$","")
                end
            end,
            active_ntp=function()
                local code,pids,overflow=web.capture({"/bin/pidof","ntpd"},512)
                if overflow then return nil end
                if code==1 then
                    return {probe_ok=true,running=false,peers={}}
                elseif code~=0 or type(pids)~="string" then
                    return nil
                end
                local peers={}
                local process_seen=false
                for pid in pids:gmatch("%d+") do
                    local raw=fs.readfile("/proc/"..pid.."/cmdline",8192)
                    if type(raw)=="string" and raw:find("^/usr/sbin/ntpd%z") then
                        process_seen=true
                        local argv={}
                        for part in raw:gmatch("([^%z]+)") do argv[#argv+1]=part end
                        local index=1
                        while index<=#argv do
                            if argv[index]=="-p" and type(argv[index+1])=="string" then
                                peers[#peers+1]=argv[index+1]
                                index=index+2
                            else
                                index=index+1
                            end
                        end
                    end
                end
                if not process_seen then return nil end
                return {probe_ok=true,running=true,peers=peers}
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
