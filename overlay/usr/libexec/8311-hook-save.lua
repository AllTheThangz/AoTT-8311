local web = require "8311.webutil"
local json = require "luci.jsonc"
local hook = require "8311.hook"
local path = arg[1]
if type(path) ~= "string" or not path:match("^/tmp/8311%-hook%-[a-f0-9]+/request%.json$") then os.exit(1) end
local form = web.read_json(path, 100000)
io.write(json.stringify(hook.save(form)))
