-- H-027: SOURCE-ONLY LuCI administrator-session handoff candidate.
-- NOT registered in the live dispatcher or firmware overlay.
-- Requires an already authenticated LuCI dispatcher context. Uses a
-- separately revalidated ubus session, not a query/cookie supplied here.
local endpoint=require "8311.history_http_readonly"
local M={}
local ROUTE="/admin/8311/history_data"
local function sid_ok(value)
    return type(value)=="string" and
        (#value==32 or #value==64) and value:match("^%x+$")~=nil
end
local function authenticated(dispatcher,util)
    if type(dispatcher)~="table" or
       type(dispatcher.context)~="table" or
       type(util)~="table" or type(util.ubus)~="function" then
        return false
    end
    local ctx=dispatcher.context
    local sid=ctx.authsession
    if not sid_ok(sid) or ctx.authuser~="root" or
       type(ctx.authacl)~="table" then
        return false
    end
    -- These calls are read-only local ubus session checks. The
    -- dispatcher has already authenticated ctx before invoking an
    -- inherited admin/8311 endpoint. Do not read sid from the request.
    local got,session=pcall(util.ubus,"session","get",{
        ubus_rpc_session=sid
    })
    if not got or type(session)~="table" or
       type(session.values)~="table" or
       session.values.username~="root" or
       type(session.values.token)~="string" or
       #session.values.token<16 then
        return false
    end
    local checked,acl=pcall(util.ubus,"session","access",{
        ubus_rpc_session=sid
    })
    return checked and type(acl)=="table"
end

local function fallback_reply(code)
    return {
        status=code,
        headers={
            ["Cache-Control"]="no-store, private, max-age=0",
            ["Content-Type"]="application/json; charset=utf-8",
            ["X-Content-Type-Options"]="nosniff",
            ["Vary"]="Cookie",
        },
        body=code==403 and '{"error":"authentication_required"}' or
             '{"error":"invalid_history_request"}',
    }
end

-- http, dispatcher and util arguments are trusted LuCI *server modules*,
-- never user-provided HTTP data. A real authenticated admin-only route
-- has to be installed and qualified separately.
function M.prepare(dispatcher,http,util,snapshot_dir,lock_dir)
    if type(http)~="table" or type(http.getenv)~="function" then
        return fallback_reply(403)
    end
    if not authenticated(dispatcher,util) then
        return fallback_reply(403)
    end
    local ok,method=pcall(http.getenv,"REQUEST_METHOD")
    local qok,query=pcall(http.getenv,"QUERY_STRING")
    if not ok or not qok or
       (query~=nil and query~="") then
        return fallback_reply(400)
    end
    return endpoint.serve_guarded_offline_ipc({
        method=method,route=ROUTE
    },function()
        return authenticated(dispatcher,util)
    end,snapshot_dir,lock_dir)
end

function M.write(dispatcher,http,util,snapshot_dir,lock_dir)
    local response=M.prepare(dispatcher,http,util,snapshot_dir,lock_dir)
    if type(http)~="table" or
       type(http.status)~="function" or
       type(http.header)~="function" or
       type(http.prepare_content)~="function" or
       type(http.write)~="function" then
        return nil,"invalid_trusted_luci_http"
    end
    http.status(response.status)
    for name,value in pairs(response.headers) do
        if name~="Content-Type" then http.header(name,value) end
    end
    http.prepare_content("application/json; charset=utf-8")
    http.write(response.body)
    return {
        status=response.status,source_only_not_deployed=true,
        actual_luci_authentication_not_hardware_qualified=true,
        no_native_probe_started=true,
        no_credential_or_cookie_echo=true,
    }
end
return M
