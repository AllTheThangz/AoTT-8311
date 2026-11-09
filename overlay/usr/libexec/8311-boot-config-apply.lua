#!/usr/bin/lua
local arguments=arg
arg=nil
local config=require "8311.config"
local tx=require "8311.boot_config_transaction"
local web=require "8311.webutil"
local json=require "luci.jsonc"
arg=arguments

local path=arguments[1]
if type(path)~="string" or
   not path:match("^/tmp/8311%-boot%-config%-[a-f0-9]+/request%.json$") then
    os.exit(1)
end
local form=web.read_json(path,100000)
if type(form)~="table" then os.exit(1) end
local controller=require "luci.controller.8311"
local snapshot,why=config.snapshot(controller.fwenvs_8311())
local result,code
if not snapshot then
    result={success=false,error=why};code=503
else
    local prepared,errors,status=config.prepare(snapshot,form)
    if not prepared then
        result={success=false,errors=errors};code=status or 422
    elseif form.mode~="apply" or prepared.route~="boot" then
        result={success=false,error="Reviewed request is not a boot-configuration transaction"};code=409
    else
        local request={}
        for _,change in ipairs(prepared.changes) do request[change.item.id]=change.raw end
        local receipt,tx_why=tx.stage(request)
        request=nil
        if not receipt then
            result={success=false,error=tx_why or "Boot configuration trial could not be staged"}
            code=409
        else
            result={
                success=true,status=receipt.status,job_id=receipt.job_id,
                fields=receipt.fields,reboot_required=receipt.reboot_required,
                confirmation_required=receipt.confirmation_required,
                timeout_seconds=receipt.timeout_seconds,
                contains_configuration_values=false,
            }
            code=200
        end
    end
end
result.http_status=code
io.write(json.stringify(result))
os.exit(0)
