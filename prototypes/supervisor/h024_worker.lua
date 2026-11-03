-- H-024 guarded foreground worker for OFFLINE SYNTHETIC qualification only.
-- This program intentionally has no production/native probe admission.
-- A real procd deployment requires a different, hardware-qualified provider.
local function die(message)
    io.stderr:write("AOTT_H024_SOURCE_WORKER_STOP:"..message.."\n")
    os.exit(24)
end
if #arg~=7 or arg[1]~="offline_synthetic" then
    die("live_mode_unavailable")
end
local vendor_root,history_root,overlay_root=arg[2],arg[3],arg[4]
local directory,stop_path=arg[5],arg[6]
local expected_parent=tonumber(arg[7])
local function plain_path(path)
    return type(path)=="string" and #path>8 and #path<220 and
           path:match("^/[%w%._%-%/]+$")~=nil and
           not path:find("%.%.",1,false) and
           not path:find("//",1,true)
end
if not plain_path(vendor_root) or not plain_path(history_root) or
   not plain_path(overlay_root) or not plain_path(directory) or
   not plain_path(stop_path) or
   not directory:match("^/var/tmp/aott%-h022%-lock%-test%-[%w%-]+$") or
   not stop_path:match("^"..directory:gsub("%-","%%-")..
                       "/stop%.%d+%.request$") or
   not expected_parent or expected_parent<1 or
   expected_parent~=math.floor(expected_parent) then
    die("invalid_offline_arguments")
end
package.path=history_root.."/?.lua;"..overlay_root.."/?.lua;"..
    vendor_root.."/usr/lib/lua/?.lua;"..
    vendor_root.."/usr/lib/lua/?/init.lua;"..package.path
package.cpath=vendor_root.."/usr/lib/lua/?.so;"..package.cpath

local ok,nixio=pcall(require,"nixio")
if not ok or type(nixio)~="table" or
   type(nixio.getppid)~="function" or
   type(nixio.nanosleep)~="function" or
   nixio.getppid()~=expected_parent then
    die("unverified_parent_process")
end
local preferences=require "8311.history_preferences"
local lifecycle=require "8311.history_lifecycle"
local profile={kind="source_only",native_qualified=true}
local initial=preferences.defaults()
local values=assert(preferences.simulate(initial,{
    sampling_enabled=true,pon_interval_seconds=60,
    host_interval_seconds=120,
},1,profile))
local session,reason=lifecycle.new(directory,values,profile,
                                   "offline_synthetic")
if not session then die(reason or "invalid_source_lifecycle") end
local started,error_code=lifecycle.start(session,100)
if not started or started.status~="running" then
    die(error_code or (started and started.status) or
        "synthetic_lock_contended")
end

-- This provider is fixed synthetic data. Never executes a native command,
-- accesses the ONU, accepts a hostname or contacts the Internet.
local BOOT="11111111-2222-4333-8444-555555555555"
local provider={uptime=100,commands=0}
function provider.read(path,max)
    if path=="/proc/sys/kernel/random/boot_id" and max==80 then
        return BOOT.."\n"
    elseif path=="/proc/uptime" and max==80 then
        return string.format("%.2f 11.00\n",provider.uptime)
    elseif path=="/sys/class/net/eth0_0/speed" and max==32 then
        return "10000\n"
    end
    error("invalid_synthetic_kernel_read")
end
function provider.run(argv,max)
    provider.commands=provider.commands+1
    local native=table.concat(argv," ")
    if native=="/usr/bin/timeout -k 1 3 /usr/bin/pon psg" and max==1024 then
        return 0,"current=51\n",false
    elseif native=="/usr/bin/timeout -k 1 4 /usr/sbin/ethtool -S eth0_0" and
           max==16384 then
        local bytes=math.floor(provider.uptime*1250000)
        return 0,"RxGoodBytes: "..tostring(bytes)..
            "\nTxGoodBytes: "..tostring(bytes*2).."\n",false
    end
    error("invalid_synthetic_process_argv")
end
local function requested_stop()
    local handle=io.open(stop_path,"r")
    if handle then
        handle:close()
        return true
    end
    return false
end
local function clean_stop()
    local closed,why=lifecycle.shutdown(session)
    if not closed then die(why or "release_unverified") end
    print("AOTT_H024_SYNTHETIC_WORKER_CLOSED")
    io.stdout:flush()
end

print("AOTT_H024_SYNTHETIC_WORKER_READY")
io.stdout:flush()
-- 300 bounded iterations, at most 60 seconds of low-priority test runtime.
-- Each 200 ms wall-clock interval advances a simulated source clock 60 s.
-- This is NOT a real production polling schedule or CPU benchmark.
for tick=0,299 do
    if nixio.getppid()~=expected_parent or requested_stop() then
        clean_stop()
        return
    end
    provider.uptime=100+tick*60
    local result,why=lifecycle.step(session,provider.uptime,provider)
    if not result then
        clean_stop()
        die(why or "lifecycle_tick_unverified")
    end
    if result.phase=="circuit_open" or result.phase=="unsafe" then
        clean_stop()
        die("circuit_open_or_unsafe")
    end
    if tick==0 then
        assert(result.status=="sample_accepted")
    end
    -- Vendor libc nanosleep blocks without spinning. The signal wrapper
    -- requests a cooperative exit through a private per-parent file.
    nixio.nanosleep(0,200000000)
end
clean_stop()
print("AOTT_H024_SYNTHETIC_FIXED_RUN_COMPLETED")
