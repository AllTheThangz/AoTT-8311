local lua_root=assert(arg[1],"overlay lua root required")
local leaf_path=assert(arg[2],"leaf path")
local key_path=assert(arg[3],"key path")
local chain_path=arg[4]
local dns=arg[5] or ""
local ips=arg[6] or ""
local expected=arg[7] or "ok"
package.path=lua_root.."/?.lua;"..package.path

package.preload["nixio.fs"]=function() return {} end
package.preload["8311.webutil"]=function() return {} end
package.preload["8311.tls_candidate"]=function()
    return {status=function() return {candidate_ready=false} end}
end

local function read(path)
    if not path or path=="" or path=="-" then return "" end
    local f=assert(io.open(path,"rb"))
    local data=f:read("*a");f:close();return data
end

local tls=require "8311.tls_import"
local record,why=tls.inspect_bytes(read(leaf_path),read(key_path),read(chain_path),dns,ips)
if expected=="ok" then
    assert(record,"TLS_IMPORT_FIXTURE expected success: "..tostring(why))
    assert(record.cert_bundle and #record.cert_bundle>0,"missing cert bundle")
    assert(record.key_data and #record.key_data>0,"missing key")
    assert(record.browser_trust_unverified==true,"browser trust caveat missing")
    assert(record.expires_utc and #record.expires_utc==15,"expiry missing")
    print("AOTT_V3_TLS_IMPORT_INSPECT_PASS chain="..tostring(record.chain_certificates))
else
    assert(record==nil,"TLS_IMPORT_FIXTURE expected refusal")
    assert(type(why)=="string" and #why>0,"refusal reason missing")
    print("AOTT_V3_TLS_IMPORT_REFUSED reason="..why)
end
