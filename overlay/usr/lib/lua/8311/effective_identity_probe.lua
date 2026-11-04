-- C-011 sensitive identity reads: fixed argv, bounded stdout, manual root-only
-- request. Do not call a setter, full environment dump, cached getter, shadow
-- password reader or a helper that resolves defaults by mutating runtime files.
local M={}
local model=require "8311.effective_identity_state"

local function read_acl(acl)
    if type(acl)~="table" or type(acl["access-group"])~="table" then return false end
    local rights=acl["access-group"]["luci-access"]
    if type(rights)~="table" then return false end
    for _,v in ipairs(rights) do
        if v=="read" or v=="write" then return true end
    end
    return false
end
function M.authorized(dispatcher,util)
    if type(dispatcher)~="table" or type(dispatcher.context)~="table" or
       type(util)~="table" or type(util.ubus)~="function" then return false end
    local ctx=dispatcher.context
    local sid=ctx.authsession
    if ctx.authuser~="root" or type(sid)~="string" or #sid~=32 or
       not sid:match("^[0-9a-fA-F]+$") or sid==string.rep("0",32) or
       not read_acl(ctx.authacl) then return false end
    local ok,session=pcall(util.ubus,"session","get",{ubus_rpc_session=sid})
    if not ok or type(session)~="table" or session.ubus_rpc_session~=sid or
       type(session.values)~="table" or session.values.username~="root" then
        return false
    end
    local checked,acl=pcall(util.ubus,"session","access",{ubus_rpc_session=sid})
    return checked and read_acl(acl) or false
end

function M.capture(adapter)
    if type(adapter)~="table" or type(adapter.environment)~="function" then
        return nil,"identity_readback_unavailable"
    end
    local observations={}
    for _,id in ipairs(model.field_ids()) do
        local max=model.limit(id)
        local ok,status,output,overflow=pcall(adapter.environment,id,max+2)
        local record={state="unavailable"}
        if ok and overflow==false and type(output)=="string" then
            if status==1 and output=="" then
                -- The selected fwenv_get explicitly uses exit 1 for absent
                -- override. A default/legacy value may still take effect.
                record.state="unset"
            elseif status==0 and #output<=max+2 then
                -- Remove ONLY one command-record terminator. Embedded or
                -- extra newlines remain invalid and never reach a response.
                local value=output:gsub("\r?\n$","")
                if #value==0 then
                    record.state="unset"
                elseif #value>max or value:find("[%z\1-\31\127]") then
                    record.state="invalid"
                else
                    record.state="present"
                    record.value=value
                end
            elseif status==0 then
                record.state="invalid"
            end
        end
        observations[id]=record
    end
    local result=model.inspect(observations)
    -- No value is attached to the response, even on an individual read error.
    return result
end

function M.live_identity(dispatcher,util)
    if not M.authorized(dispatcher,util) then return nil,"forbidden" end
    local ok,report=pcall(function()
        local web=require "8311.webutil"
        return M.capture({environment=function(id,limit)
            if not model.limit(id) then return nil end
            return web.capture({"/usr/bin/timeout","-k","1","3",
                "/usr/sbin/fwenv_get","--8311",id},limit)
        end})
    end)
    -- A revoked/expired session must not receive even a presence result.
    if not M.authorized(dispatcher,util) then return nil,"forbidden" end
    if not ok or type(report)~="table" or report.schema~=1 or
       report.no_identity_exported~=true or report.no_credential_hash_exported~=true or
       report.no_raw_environment_exported~=true then
        return nil,"identity_readback_unavailable"
    end
    return report
end
return M
