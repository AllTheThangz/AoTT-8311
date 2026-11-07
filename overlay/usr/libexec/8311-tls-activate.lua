#!/usr/bin/lua
local activation=require "8311.tls_activation"
local nixio=require "nixio"
if #arg~=2 then os.exit(64) end
-- Give the HTTPS controller response time to leave the old connection before
-- the detached worker restarts uhttpd.
nixio.nanosleep(2,0)
local result,why=activation.activate(arg[1],arg[2])
if not result then
    io.stderr:write("TLS activation failed safely: "..tostring(why).."\n")
    os.exit(1)
end
if result.status=="confirmed" then
    print("TLS activation confirmed. Persistent rollback material removed.")
    os.exit(0)
end
if result.status=="rolled_back" then
    print("TLS activation confirmation expired or failed. Previous HTTPS certificate restored.")
    os.exit(2)
end
io.stderr:write("TLS activation ended in an unknown state.\n")
os.exit(1)
