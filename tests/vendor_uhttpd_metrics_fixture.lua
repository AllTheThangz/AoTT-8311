-- Execute the exact extracted vendor uhttpd Lua handler with synthetic
-- request metadata. No real sockets, network listeners or device state.
local vendor_path=assert(arg[1])
local observed, writes={}, {}
luci={}
package.preload["nixio.util"] = function() return {} end
package.preload["luci.http"] = function()
    luci.http={
        Request=function(env, recv, sink)
            assert(type(env)=="table" and type(recv)=="function")
            observed=env
            return {}
        end
    }
    return luci.http
end
package.preload["luci.sys"] = function()
    luci.sys={}
    return luci.sys
end
package.preload["luci.dispatcher"] = function()
    luci.dispatcher={httpdispatch=function() return end}
    return luci.dispatcher
end
package.preload["luci.ltn12"] = function()
    luci.ltn12={sink={file=function() return function() end end}}
    return luci.ltn12
end
uhttpd={
    recv=function() return 0, "" end,
    send=function(value) writes[#writes+1]=value end,
}
assert(loadfile(vendor_path))()
assert(type(handle_request)=="function")
local synthetic_token=string.rep("a",64)
local request={
    CONTENT_LENGTH="0",CONTENT_TYPE="",REQUEST_METHOD="GET",
    REQUEST_URI="/cgi-bin/luci/8311/metrics",
    PATH_INFO="/8311/metrics",SCRIPT_NAME="/cgi-bin/luci",
    SERVER_PROTOCOL="HTTP/1.1",QUERY_STRING="forged=value",
    DOCUMENT_ROOT="/www",HTTPS="on",REDIRECT_STATUS="",
    REMOTE_ADDR="192" .. ".0.2.40",
    REMOTE_NAME="",REMOTE_PORT="54000",REMOTE_USER="",
    SERVER_ADDR="192" .. ".0.2.1",
    SERVER_NAME="",SERVER_PORT="443",
    headers={
        ["x-aott-metrics-token"]=synthetic_token,
        ["x-forwarded-for"]="198" .. ".51.100.17",
        ["content-type"]="text/plain",
    }
}
handle_request(request)
assert(observed.HTTP_X_AOTT_METRICS_TOKEN==synthetic_token)
assert(observed.HTTPS=="on")
assert(observed.REMOTE_ADDR==request.REMOTE_ADDR)
assert(observed.SERVER_ADDR==request.SERVER_ADDR)
assert(observed.REQUEST_METHOD=="GET")
assert(observed.HTTP_X_FORWARDED_FOR==request.headers["x-forwarded-for"])
assert(observed.HTTP_X_FORWARDED_FOR~=observed.REMOTE_ADDR)
assert(observed.QUERY_STRING=="forged=value")
assert(observed.HTTP_X_AOTT_METRICS_TOKEN~=observed.QUERY_STRING)
request.HTTPS="off";request.REMOTE_ADDR="192" .. ".0.2.41"
request.headers["x-aott-metrics-token"]=nil
handle_request(request)
assert(observed.HTTPS=="off")
assert(observed.HTTP_X_AOTT_METRICS_TOKEN==nil)
assert(observed.REMOTE_ADDR==request.REMOTE_ADDR)
print("VENDOR_UHTTPD_ENVIRONMENT_OFFLINE_PASS")
