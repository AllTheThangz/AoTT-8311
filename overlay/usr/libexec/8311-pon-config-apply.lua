#!/usr/bin/lua
-- Fixed private PON/OMCI job entrypoint. Subscriber values remain inside the
-- root-owned request file and never enter process argv or public output.
local fs=require "nixio.fs"
local json=require "luci.jsonc"
local tx=require "8311.pon_config_transaction"
local config=require "8311.config"

local dir=arg[1]
local id=type(dir)=="string" and dir:match("^/tmp/8311%-web%-jobs/([0-9a-f]+)$")
if not id or #id~=32 then os.exit(2) end
local dst=fs.lstat(dir)
if not dst or dst.type~="dir" or dst.uid~=0 or dst.gid~=0 or dst.modedec~=700 then os.exit(2) end
local path=dir.."/request.json"
local st=fs.lstat(path)
if not st or st.type~="reg" or st.uid~=0 or st.gid~=0 or
   st.modedec~=600 or st.nlink~=1 or st.size<1 or st.size>32768 then os.exit(2) end
local raw=fs.readfile(path,32769)
if type(raw)~="string" or #raw~=st.size then os.exit(2) end
local ok,request=pcall(json.parse,raw)
raw=nil
if not ok or type(request)~="table" or request.schema~=1 or request.id~=id or
   request.kind~="pon_apply" or type(request.args)~="table" or
   type(request.args.revision)~="string" or type(request.args.changes)~="table" then os.exit(2) end
local controller=require "luci.controller.8311"
local snapshot=config.snapshot(controller.fwenvs_8311())
if not snapshot or snapshot.revision~=request.args.revision then
    request=nil
    os.exit(3)
end
local changes=request.args.changes
local called,receipt,why=pcall(tx.apply,dir,changes)
changes=nil
request=nil
if not called or type(receipt)~="table" then os.exit(1) end
local public={
    schema=receipt.schema,status=receipt.status,
    confirmation_required=receipt.confirmation_required,
    local_runtime_verified=receipt.local_runtime_verified,
    pon_registered_o5_1=receipt.pon_registered_o5_1,
    rollback_verified=receipt.rollback_verified,
    olt_per_field_effect_proven=false,
    contains_configuration_values=false,
}
io.write(json.stringify(public),"\n")
if receipt.status=="PON_TRANSACTION_CONFIRMED" or
   receipt.status=="PON_TRANSACTION_NO_CHANGE" then os.exit(0) end
if receipt.status=="PON_TRANSACTION_ROLLED_BACK" then os.exit(2) end
os.exit(1)
