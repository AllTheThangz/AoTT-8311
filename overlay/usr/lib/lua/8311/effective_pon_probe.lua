-- AoTT-8311 C-011: read-only native PON configuration inspector.
-- Authenticated administrator use ONLY. Fixed UCI + noncredential env keys.
-- Only PON state code is extracted from native status output. Raw status
-- output and subscriber registration credentials are NEVER returned.
local M={}
local model=require "8311.effective_pon_state"
local UCI_OPTIONS={
    pon_mode={"gpon","ponip","pon_mode"},
    omcc_version={"omci","default","omcc_version"},
    iop_mask={"gpon","ponip","iop_mask"},
    mib_file={"omci","default","mib_file"},
}

local function clean(value)
    if type(value)~="string" or #value>130 then return nil end
    value=value:gsub("[\r\n]+$","")
    if value:find("[%z\1-\31\127]") then return nil end
    return value
end

function M.capture(adapter)
    if type(adapter)~="table" or
       type(adapter.environment)~="function" or
       type(adapter.configured)~="function" or
       type(adapter.pon_status)~="function" then
        return nil,"invalid_readonly_pon_adapter"
    end
    local function safe(fn,...)
        local ok,value=pcall(fn,...)
        if ok then return value end
        return nil
    end
    local saved={}
    local configured={}
    for _,id in ipairs(model.fields) do
        saved[id]=clean(safe(adapter.environment,id))
        local key=UCI_OPTIONS[id]
        configured[id]=clean(safe(adapter.configured,
                             key[1],key[2],key[3]))
    end
    local native=safe(adapter.pon_status)
    local state
    if type(native)=="string" then
        state=model.parse_pon_status(native)
    end
    return model.inspect(saved,configured,state)
end

-- Source-only hook. Never register as anonymous collector data.
-- Privileged caller MUST inherit authenticated LuCI admin session.
function M.live_pon()
    local ok,record=pcall(function()
        local web=require "8311.webutil"
        local uci=require("luci.model.uci").cursor()
        local allowed={}
        for _,id in ipairs(model.fields) do allowed[id]=true end
        local function bounded(argv,size)
            local code,result,overflow=web.capture(argv,size)
            if code==0 and not overflow and type(result)=="string" then
                return result
            end
        end
        return M.capture({
            environment=function(id)
                if not allowed[id] then return nil end
                return bounded({"/usr/bin/timeout","-k","1","3",
                    "/usr/sbin/fwenv_get","--8311",id},256)
            end,
            configured=function(pkg,section,option)
                -- Only exact map entries are accepted.
                local approved=false
                for _,keys in pairs(UCI_OPTIONS) do
                    if keys[1]==pkg and keys[2]==section and
                       keys[3]==option then approved=true end
                end
                if not approved then return nil end
                return uci:get(pkg,section,option)
            end,
            pon_status=function()
                return bounded({"/usr/bin/timeout","-k","1","3",
                               "/usr/bin/pon","psg"},1024)
            end,
        })
    end)
    if not ok or type(record)~="table" or record.schema~=1 then
        return nil,"read_only_pon_probe_unavailable"
    end
    return record
end

M.uci_options=UCI_OPTIONS
return M
