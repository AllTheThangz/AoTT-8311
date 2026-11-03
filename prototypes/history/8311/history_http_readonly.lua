-- H-026: Source-only authenticated read-only history response contract.
-- No LuCI route registration, network listener or native PON probe.
local M={}
local MAX_BYTES=65536
local RESPONSE={
    ["Cache-Control"]="no-store, private, max-age=0",
    ["X-Content-Type-Options"]="nosniff",
    ["Content-Security-Policy"]="default-src 'none'",
    ["Referrer-Policy"]="no-referrer",
    ["Vary"]="Cookie",
}
local function headers()
    local h={}
    for key,value in pairs(RESPONSE) do h[key]=value end
    h["Content-Type"]="application/json; charset=utf-8"
    return h
end
local function error_reply(code)
    local body=code==403 and
        '{"error":"authentication_required"}' or
        (code==405 and '{"error":"method_not_allowed"}' or
         (code==400 and '{"error":"invalid_history_request"}' or
          '{"error":"history_not_available"}'))
    local head=headers()
    head["Content-Length"]=tostring(#body)
    if code==405 then head["Allow"]="GET" end
    return {status=code,headers=head,body=body,
        server_uses_bounded_cached_history_only=true,
        source_only_not_deployed=true}
end
-- Authentication callback MUST come from a trusted LuCI dispatcher
-- integration. Never accepts a cookie, API token, or auth boolean from
-- the user request. Untrusted parameters cannot select storage paths.
function M.serve(request,verify_admin,read_snapshot)
    if type(verify_admin)~="function" then return error_reply(403) end
    local ok,authorized=pcall(verify_admin)
    if not ok or authorized~=true then return error_reply(403) end
    if type(request)~="table" or
       request.method~="GET" or
       request.route~="/admin/8311/history_data" then
        return error_reply(405)
    end
    for key in pairs(request) do
        if key~="method" and key~="route" and key~="range" then
            return error_reply(400)
        end
    end
    if request.range~=nil and request.range~="hour" then
        -- The one volatile projection contains all five window summaries.
        -- A browser switches ranges locally without creating new PON reads.
        return error_reply(400)
    end
    if type(read_snapshot)~="function" then return error_reply(503) end
    local read_ok,raw=pcall(read_snapshot)
    if not read_ok or type(raw)~="string" or #raw<2 or
       #raw>MAX_BYTES then return error_reply(503) end
    -- Never relay caller-supplied or corrupt JSON just because an
    -- injected read function returned bytes. Revalidate the exact
    -- H-016 export shape before the HTTP response leaves this boundary.
    local checked,decoded=pcall(function()
        local parser=require "luci.jsonc"
        return parser.parse(raw)
    end)
    if not checked or type(decoded)~="table" then
        return error_reply(503)
    end
    local canonical=require "8311.history_export"
    local rebuilt=canonical.encode_checked_projection(decoded)
    if rebuilt~=raw then return error_reply(503) end
    local h=headers()
    h["Content-Length"]=tostring(#raw)
    return {
        status=200,headers=h,body=raw,
        source_only_not_deployed=true,
        server_uses_bounded_cached_history_only=true,
        no_on_demand_native_poll=true,
        currentness_not_proven=true,
        device_or_firmware_write=false,
    }
end
-- No HTTP integration exists yet; this binds the validated offline
-- vendor-MIPS reader without making a public endpoint.
function M.serve_offline_ipc(request,verify_admin,directory)
    local bridge=require "8311.history_snapshot_ipc"
    return M.serve(request,verify_admin,function()
        return bridge.read(directory,"offline_synthetic")
    end)
end
return M
