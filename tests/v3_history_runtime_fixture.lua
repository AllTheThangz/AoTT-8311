local overlay=assert(arg[1],"overlay lua root required")
package.path=overlay.."/?.lua;"..package.path

local sampler=require "8311.history_sampler"
local exporter=require "8311.history_export"
local shape=require "8311.history_snapshot_shape"
local state=assert(sampler.new({max_samples=30,max_events=16}))
local function sample(t,rx,tx)
    return {
        boot="11111111-2222-4333-8444-555555555555",
        uptime=t,source="eth0_0",pon_state=51,ethernet_mbps=10000,
        eth={RxGoodBytes=tostring(rx),TxGoodBytes=tostring(tx)},
        observed={pon=true,host=true},
    }
end
assert(sampler.ingest_selected(state,sample(100,1000000,2000000)))
assert(sampler.ingest_selected(state,sample(160,61000000,122000000)))
local live=assert(exporter.project(state,"hour",100,"local_runtime"))
assert(live.kind=="aott_local_history")
assert(live.source_only_not_live==false)
assert(live.actual_isp_uptime_unverified==true)
assert(live.history_is_volatile==true)
assert(shape.validate(live)==true)
local encoded=assert(exporter.export_json(state,"hour",100,"local_runtime"))
assert(encoded:find('"kind":"aott_local_history"',1,true))
assert(encoded:find('"source_only_not_live":false',1,true))
assert(not encoded:find('"source_only_not_live":true',1,true))
local canonical=assert(exporter.encode_checked_projection(live))
assert(canonical==encoded)

package.loaded["8311.history_config"]=nil
package.loaded["luci.model.uci"]=nil
package.loaded["8311.webutil"]=nil
package.loaded["nixio.fs"]=nil
package.loaded["8311.history_process_lock"]=nil
package.preload["luci.model.uci"]=function()
    return {cursor=function() return {} end}
end
package.preload["8311.webutil"]=function()
    return {digest_text=function() return string.rep("a",64) end}
end
package.preload["nixio.fs"]=function()
    return {stat=function() return nil end}
end
package.preload["8311.history_process_lock"]=function()
    return {PRODUCTION_DIR="/run/aott-history",
            writer_present=function() return false,"not_started" end}
end
local config=require "8311.history_config"
local base={
    revision=string.rep("a",64),enabled="1",
    pon_interval_seconds="60",host_interval_seconds="30",
    ram_sample_limit="120",ram_event_limit="128",
}
local ok=assert(config.validate(base))
assert(ok.enabled=="1" and ok.host_interval_seconds=="30")
local bad={}
for k,v in pairs(base) do bad[k]=v end
bad.pon_interval_seconds="1"
local rejected,why=config.validate(bad)
assert(rejected==nil and why=="Invalid PON sampling interval")
bad={}
for k,v in pairs(base) do bad[k]=v end
bad.ram_sample_limit="721"
rejected,why=config.validate(bad)
assert(rejected==nil and why=="RAM sample limit must be 30 through 720")
print("AOTT_V3_HISTORY_RUNTIME_FIXTURE_PASS")
