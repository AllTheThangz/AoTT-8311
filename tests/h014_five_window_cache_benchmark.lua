-- H-014 repeatable, offline-only cached five-window query benchmark.
-- Source fixture with fake byte counters only; no native commands or devices.
local root=assert(arg[1],"Prototype Lua source root required")
package.path=root.."/?.lua;"..package.path
local sampler=require "8311.history_sampler"
local state=assert(sampler.new({max_samples=720,max_events=128}))
for i=1,720 do
    local record={
        boot="synthetic-boot",source="eth0_0",uptime=i,
        pon_state=51,ethernet_mbps=10000,
        eth={RxGoodBytes=tostring(i*125000),TxGoodBytes=tostring(i*250000)},
    }
    local accepted,reason=sampler.ingest(state,record)
    assert(accepted,reason)
end
collectgarbage("collect")
local baseline_kib=collectgarbage("count")
local initial_cpu=os.clock()
for i=1,200 do
    local windows=assert(sampler.history_windows(state))
    assert(windows.hour.rx.interval_count==719)
    assert(windows.ninety_days.tx.interval_count==719)
    assert(windows.hour.customer_wan_throughput_proven==false)
    assert(windows.ninety_days.window_complete==false)
    assert(windows.hour.source=="eth0_0")
end
local measured_cpu_seconds=os.clock()-initial_cpu
collectgarbage("collect")
local retained_heap_kib=collectgarbage("count")-baseline_kib
assert(measured_cpu_seconds>=0)
assert(retained_heap_kib>=-64 and retained_heap_kib<256)
assert(state.samples_count==720 and state.events_count==0)
print(string.format(
    "AOTT_H014_FIVE_WINDOW_CACHE_BENCH_PASS queries=200 samples=720 cpu_seconds=%.5f retained_heap_kib=%.2f",
    measured_cpu_seconds,retained_heap_kib
))
