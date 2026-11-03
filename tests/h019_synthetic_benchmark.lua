-- H-019: synthetic, single-process resource qualification.
-- NO native provider, network, flash, system commands, timers or device access.
-- Run under host Lua or the previously extracted vendor Lua in QEMU.
local root=assert(arg[1],"Prototype root is required")
local iterations=tonumber(arg[2])
assert(iterations and iterations==math.floor(iterations) and
       iterations>=100 and iterations<=20000,"Invalid bounded iteration count")
package.path=root.."/?.lua;"..package.path
package.preload["8311.effective_pon_state"]=function()
    -- Import the existing, tested source model rather than duplicating its parser.
    return assert(loadfile(assert(arg[3],"PON model path is required")))()
end
local sampler=require "8311.history_sampler"
local reader=require "8311.history_native_probe"
local boot="11111111-2222-4333-8444-555555555555"
local state=assert(sampler.new({max_samples=120,max_events=128}))
local N=iterations
local current,uptime_reads=0,0
local command_calls,read_calls,unavailable=0,0,0
local function pon() return current % 100==0 and 60 or 51 end
local function speed() return current % 100==0 and 1000 or 10000 end
local provider={
    read=function(path,limit)
        read_calls=read_calls+1
        if path=="/proc/sys/kernel/random/boot_id" then
            assert(limit==80)
            return boot.."\n"
        end
        if path=="/proc/uptime" then
            assert(limit==80)
            uptime_reads=uptime_reads+1
            local end_read=(uptime_reads%2)==0
            return string.format("%.2f 100.00\n",
                current*10 + 100 + (end_read and 0.1 or 0))
        end
        if path=="/sys/class/net/eth0_0/speed" then
            assert(limit==32)
            return tostring(speed()).."\n"
        end
        error("Non-whitelisted synthetic path")
    end,
    run=function(argv,limit)
        command_calls=command_calls+1
        local command=table.concat(argv," ")
        if command=="/usr/bin/timeout -k 1 3 /usr/bin/pon psg" then
            assert(limit==1024)
            return 0,"current="..tostring(pon()).."\n",false
        end
        if command=="/usr/bin/timeout -k 1 4 /usr/sbin/ethtool -S eth0_0" then
            assert(limit==16384)
            return 0,"NIC statistics:\nRxGoodBytes: "..tostring(current*1250000)..
                "\nTxGoodBytes: "..tostring(current*625000).."\n",false
        end
        error("Non-whitelisted synthetic command")
    end,
}
collectgarbage("collect")
local initial_heap_kib=collectgarbage("count")
local peak_heap_kib=initial_heap_kib
local cpu_start=os.clock()
local good_rates=0
for i=1,N do
    current=i
    local receipt,reason=reader.collect_one(state,provider)
    assert(receipt,reason or "Missing synthetic receipt")
    assert(receipt.no_device_write and
           receipt.source_only_not_hardware_qualified)
    assert(receipt.availability.proves_subscriber_internet==false)
    if i==1 then
        assert(receipt.status=="baseline" and not receipt.has_rate)
    else
        assert(receipt.status=="valid_interval" and receipt.has_rate)
        good_rates=good_rates+1
    end
    local heap=collectgarbage("count")
    if heap>peak_heap_kib then peak_heap_kib=heap end
end
local elapsed_cpu_seconds=os.clock()-cpu_start
collectgarbage("collect")
local retained_heap_kib=collectgarbage("count")-initial_heap_kib
local samples=assert(sampler.recent(state,"samples",100))
local events=assert(sampler.recent(state,"events",100))
assert(#samples==100 and state.samples_count==120)
assert(#events<=100 and state.events_count<=128)
assert(state.accepted==N and good_rates==N-1)
assert(read_calls==N*5 and command_calls==N*2)
assert(unavailable==0)
assert(samples[#samples].has_rate==nil and
       samples[#samples].boot==nil and
       samples[#samples].password==nil)
assert(samples[#samples].rate_source=="hardware_ethernet_byte_counters")
assert(samples[#samples].direction=="host_interface_rx_tx")
assert(retained_heap_kib < 256,"RAM ring retention exceeded 256 KiB in synthetic fixture")
assert(elapsed_cpu_seconds>=0)
print(string.format(
    "AOTT_H019_SYNTHETIC_BENCH_PASS iterations=%d cpu_seconds=%.5f heap_retained_kib=%.2f heap_peak_kib=%.2f reads=%d commands=%d samples=%d events=%d",
    N,elapsed_cpu_seconds,retained_heap_kib,peak_heap_kib,
    read_calls,command_calls,state.samples_count,state.events_count))
