local arguments = arg
-- This firmware's dual-use base64.lua prints command-line arguments on require.
-- Module loading in this worker must not contaminate its JSON response.
arg = nil
local config = require "8311.config"
local web = require "8311.webutil"
local json = require "luci.jsonc"
arg = arguments
if arguments[1] == "--boot-snapshot" then os.exit(config.boot_snapshot() and 0 or 1) end
local path = arguments[1]
if type(path) ~= "string" or not path:match("^/tmp/8311%-config%-[a-f0-9]+/request%.json$") then os.exit(1) end
local form = web.read_json(path, 32768)
local controller = require "luci.controller.8311"
local snapshot, err = config.snapshot(controller.fwenvs_8311())
local result, code
if not snapshot then result={success=false,error=err}; code=503 else
	local prepared, errors, status = config.prepare(snapshot, form)
	if not prepared then result={success=false,errors=errors}; code=status
	elseif form.mode == "preview" then result={success=true,diff=prepared.diff,revision=snapshot.revision}; code=200
	else result=config.apply(snapshot, prepared); code=result.success and 200 or 502 end
end
result.http_status=code
io.write(json.stringify(result))
os.exit(0)
