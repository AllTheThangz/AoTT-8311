-- H-022 guarded H-021 collector, with real vendor-MIPS fcntl owner.
-- All native observations are injected fake results, not actual ONU calls.
local root=assert(arg[1],"Extracted vendor rootfs required")
local library=assert(arg[2],"Source-only history Lua root required")
local overlay=assert(arg[3],"Overlay Lua root required")
local mode=assert(arg[4],"Test mode required")
local directory=assert(arg[5],"Private lock directory required")
package.path=library.."/?.lua;"..overlay.."/?.lua;"..
    root.."/usr/lib/lua/?.lua;"..
    root.."/usr/lib/lua/?/init.lua;"..package.path
package.cpath=root.."/usr/lib/lua/?.so;"..package.cpath
local preferences=require "8311.history_preferences"
local protected=require "8311.history_guarded_collector"
local cap={kind="source_only",native_qualified=true}
local state=preferences.defaults()
local configured=assert(preferences.simulate(state,{
    sampling_enabled=true,pon_interval_seconds=60,
    host_interval_seconds=120,
},1,cap))
local invalid_mode,mode_reason=protected.new(
    directory,configured,cap,"run_live")
assert(invalid_mode==nil and
       mode_reason=="hardware_admission_not_qualified")
local rejected,rejection=protected.new(
    directory,configured,{kind="source_only",native_qualified=false},
    "offline_synthetic")
if rejected~=nil then error("unqualified_device_profile_accepted") end
assert(rejection=="hardware_not_directly_qualified" or
       rejection=="collector_held_by_other_process")
local function fake()
    local provider={uptime=100,pon=51,commands=0}
    local BOOT="11111111-2222-4333-8444-555555555555"
    function provider.read(path,max)
        if path=="/proc/sys/kernel/random/boot_id" then
            return BOOT.."\n"
        elseif path=="/proc/uptime" then
            return tostring(provider.uptime).." 12.00\n"
        elseif path=="/sys/class/net/eth0_0/speed" then
            return "10000\n"
        end
        error("UNKNOWN_KERNEL_READ")
    end
    function provider.run(argv,max)
        provider.commands=provider.commands+1
        local command=table.concat(argv," ")
        if command=="/usr/bin/timeout -k 1 3 /usr/bin/pon psg" then
            return 0,"current="..provider.pon.."\n",false
        elseif command=="/usr/bin/timeout -k 1 4 /usr/sbin/ethtool -S eth0_0" then
            local rx=math.floor(provider.uptime*1250000)
            return 0,"RxGoodBytes: "..rx..
                "\nTxGoodBytes: "..(rx*2).."\n",false
        end
        error("UNKNOWN_NATIVE_COMMAND")
    end
    return provider
end

local owner,why=protected.new(directory,configured,cap,"offline_synthetic")
if mode=="guarded_try" and not owner then
    assert(why=="collector_held_by_other_process")
    print("AOTT_H022_GUARDED_BUSY")
    return
end
assert(owner,why)
local d=assert(protected.status(owner))
assert(d.exclusive_kernel_owner and d.source_only_not_live)
assert(d.independent_channel_cadences_implemented)
assert(d.pon_interval_seconds==60 and d.host_interval_seconds==120)
local other,why=protected.new(directory,configured,cap,"offline_synthetic")
assert(other==nil and why=="collector_already_owned_in_process")
local provider=fake()
local first=assert(protected.tick(owner,100,provider))
assert(first.status=="sample_accepted")
provider.uptime=160
local one=assert(protected.tick(owner,160,provider))
assert(one.due_pon and not one.due_host)
provider.uptime=220
local rate=assert(protected.tick(owner,220,provider))
assert(rate.has_rate==true)
local doc=assert(protected.export_json(owner,"hour"))
assert(not doc:find("11111111-2222",1,true))
assert(doc:find('"not_sampled"',1,true))
local rows=assert(protected.view(owner,"hour"))
assert(rows.windows.hour.rx.covered_seconds==120)
assert(rows.actual_isp_uptime_unverified==true)
assert(provider.commands==5)
print("AOTT_H022_GUARDED_READY")
io.stdout:flush()
if mode=="guarded_hold" or mode=="guarded_hold_exit" then
    io.read("*l")
end
if mode=="guarded_hold_exit" then
    print("AOTT_H022_GUARDED_EXIT_WITHOUT_CLOSE")
    os.exit(0)
end
local finished=assert(protected.close(owner))
assert(finished.lock_file_is_never_unlinked)
assert(protected.status(owner)==nil)
assert(protected.tick(owner,240,provider)==nil)
print("AOTT_H022_GUARDED_RELEASED")
