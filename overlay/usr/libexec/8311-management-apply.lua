#!/usr/bin/lua
-- Fixed management job entrypoint. Reads the private root-owned job request
-- from disk so management addresses and MAC values never appear in argv.
local fs=require "nixio.fs"
local json=require "luci.jsonc"
local tx=require "8311.management_transaction"

local dir=arg[1]
local id=type(dir)=="string" and dir:match("^/tmp/8311%-web%-jobs/([0-9a-f]+)$")
if not id or #id~=32 then os.exit(2) end
local dst=fs.lstat(dir)
if not dst or dst.type~="dir" or dst.uid~=0 or dst.gid~=0 or dst.modedec~=700 then os.exit(2) end
local path=dir.."/request.json"
local st=fs.lstat(path)
if not st or st.type~="reg" or st.uid~=0 or st.gid~=0 or
   st.modedec~=600 or st.nlink~=1 or st.size<1 or st.size>16384 then os.exit(2) end
local raw=fs.readfile(path,16385)
if type(raw)~="string" or #raw~=st.size then os.exit(2) end
local ok,request=pcall(json.parse,raw)
raw=nil
if not ok or type(request)~="table" or request.schema~=1 or request.id~=id or
   request.kind~="management_apply" or type(request.args)~="table" then os.exit(2) end
local called,receipt,why=pcall(tx.apply,dir,request.args)
request=nil
if not called or type(receipt)~="table" then
    os.exit(1)
end
local public={
    schema=receipt.schema,status=receipt.status,
    confirmation_required=receipt.confirmation_required,
    runtime_verified=receipt.runtime_verified,
    rollback_verified=receipt.rollback_verified,
    contains_configuration_values=false,
}
io.write(json.stringify(public),"\n")
if receipt.status=="MANAGEMENT_TRANSACTION_CONFIRMED" or
   receipt.status=="MANAGEMENT_TRANSACTION_NO_CHANGE" then
    os.exit(0)
end
if receipt.status=="MANAGEMENT_TRANSACTION_ROLLED_BACK" then os.exit(2) end
os.exit(1)
