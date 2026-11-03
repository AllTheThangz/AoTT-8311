-- H-027 LuCI route candidate through real vendor-MIPS source runtime.
-- A simulated trusted dispatcher/context/ubus call tests auth semantics.
-- Actual subscriber credentials, device and live LuCI are never used.
local vendor=assert(arg[1])
local history=assert(arg[2])
local overlay=assert(arg[3])
local lockdir=assert(arg[4])
local snapdir=assert(arg[5])
local mode=assert(arg[6])
package.path=history.."/?.lua;"..overlay.."/?.lua;"..
    vendor.."/usr/lib/lua/?.lua;"..
    vendor.."/usr/lib/lua/?/init.lua;"..package.path
package.cpath=vendor.."/usr/lib/lua/?.so;"..package.cpath
local route=require "8311.history_luci_route_candidate"
local checks=0
local SID=string.rep("a",32)
local function ok(value,label)
    checks=checks+1
    assert(value,"H027_LUCI_SESSION_TEST_FAILED:"..label)
end
local function eq(a,b,label)ok(a==b,label)end
local ctx={authsession=SID,authuser="root",authacl={}}
local dispatcher={context=ctx}
local service={get_count=0,access_count=0,expired=false,
    bad_session=false,raise=false}
function service.ubus(object,command,request)
    ok(object=="session","only_session_UBUS")
    eq(request.ubus_rpc_session,SID,"sid_only_from_dispatcher")
    if service.raise then error("PRIVATE_SESSION_FAILURE") end
    if command=="get" then
        service.get_count=service.get_count+1
        if service.expired then return nil end
        return {values={
            username=service.bad_session and "guest" or "root",
            token=string.rep("1",32)
        }}
    elseif command=="access" then
        service.access_count=service.access_count+1
        return {access=true}
    end
    error("UNEXPECTED_UBUS_ACTION")
end
local method,query="GET",nil
local result={status=nil,head={},mime=nil,body=nil}
local http={}
function http.getenv(name)
    if name=="REQUEST_METHOD" then return method end
    if name=="QUERY_STRING" then return query end
    error("UNEXPECTED_SOURCE_ENVIRONMENT")
end
function http.status(value) result.status=value end
function http.header(k,v)result.head[k]=v end
function http.prepare_content(v)result.mime=v end
function http.write(v)result.body=v end
local function write()
    result={status=nil,head={},mime=nil,body=nil}
    local receipt=assert(route.write(dispatcher,http,service,snapdir,lockdir))
    eq(receipt.status,result.status,"status_written")
    eq(receipt.source_only_not_deployed,true,"not_installed")
    eq(receipt.no_native_probe_started,true,"never_calls_pon")
    ok(type(result.body)=="string","body_string")
    return result
end
local valid=write()
if mode=="inactive" then
    eq(valid.status,503,"active_lock_required")
    ok(valid.body:find("history_not_available",1,true)~=nil,
       "no_stale_history_returned")
else
    eq(valid.status,200,"valid_dispatcher_session_get")
    local parsed=require("luci.jsonc").parse(valid.body)
    eq(parsed.kind,"aott_source_only_history","strict_cached_history")
    eq(parsed.actual_isp_uptime_unverified,true,
       "no_ISP_status_inferred")
    eq(valid.head["Cache-Control"],"no-store, private, max-age=0",
       "cache_disabled")
    eq(valid.mime,"application/json; charset=utf-8","response_content_type")
end
eq(service.get_count,2,"ubus_get_rechecked_on_read")
eq(service.access_count,2,"ubus_acl_rechecked_on_read")
local invoked=service.get_count
ctx.authuser="guest"
eq(write().status,403,"nonroot_rejected")
eq(service.get_count,invoked,"guest_not_sent_to_session_backend")
ctx.authuser="root"
ctx.authsession="forged-unvalidated-session"
eq(write().status,403,"invalid_sid_rejected")
eq(service.get_count,invoked,"bad_sid_rejected_before_UBUS")
ctx.authsession=SID
ctx.authacl=nil
eq(write().status,403,"missing_trusted_acl_rejected")
ctx.authacl={}
service.expired=true
eq(write().status,403,"UBUS_expired_session_rejected")
service.expired=false
service.bad_session=true
eq(write().status,403,"UBUS_username_mismatch_rejected")
service.bad_session=false
service.raise=true
local failed=write()
eq(failed.status,403,"UBUS_exception_rejected")
ok(not failed.body:find("PRIVATE_SESSION_FAILURE",1,true),
   "private_auth_error_redacted")
service.raise=false
query="path=../../etc/passwd"
eq(write().status,400,"unexpected_query_refused")
query=nil
method="POST"
eq(write().status,405,"read_only_route")
method="GET"
local missing_http=route.prepare(dispatcher,{},service,snapdir,lockdir)
eq(missing_http.status,403,"untrusted_HTTP_instance_rejected")
-- Never echo session or credential material in a prepared response.
for _,sample in ipairs({failed,write()}) do
    ok(not sample.body:find(SID,1,true),"session_ID_never_echoed")
    ok(not sample.body:find(string.rep("1",32),1,true),
       "UBUS_token_never_echoed")
end
print("AOTT_H027_LUCI_SOURCE_GATE_PASS checks="..checks)
