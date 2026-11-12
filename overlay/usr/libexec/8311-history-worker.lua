#!/usr/bin/lua
-- AoTT-8311 V3 foreground local-history worker. Read-only device sampling.
local fs=require "nixio.fs"
local nixio=require "nixio"
local web=require "8311.webutil"
local config=require "8311.history_config"
local lock=require "8311.history_process_lock"
local sampler=require "8311.history_sampler"
local native=require "8311.history_native_probe"
local snapshot=require "8311.history_live_snapshot"

local function stop(message)
    io.stderr:write("aott-history: "..tostring(message).."\n")
    os.exit(23)
end
local function uptime()
    local raw=fs.readfile("/proc/uptime",80)
    local value=type(raw)=="string" and raw:match("^%s*(%d+%.?%d*)%s+")
    value=tonumber(value)
    if not value or value<0 or value>1e12 then return nil end
    return value
end

local runtime,why=config.runtime()
if not runtime then stop(why) end
if not fs.stat(lock.PRODUCTION_DIR) then stop("runtime_directory_missing") end
local owner,lock_info=lock.acquire(lock.PRODUCTION_DIR)
if not owner then stop(lock_info) end
local state,reason=sampler.new({
    max_samples=runtime.ram_sample_limit,
    max_events=runtime.ram_event_limit,
})
if not state then stop(reason) end
local invalid,invalid_why=snapshot.invalidate(owner)
if not invalid then stop(invalid_why) end

local provider={
    read=function(path,maximum) return fs.readfile(path,maximum) end,
    run=function(argv,maximum) return web.capture(argv,maximum) end,
}
local next_pon=0
local next_host=0
local next_optical=0
local publication=nil
local consecutive_failures=0

while true do
    local now=uptime()
    if not now then stop("monotonic_time_unavailable") end
    local selected={
        pon=now>=next_pon,
        host=now>=next_host,
        optical=runtime.optical_enabled and now>=next_optical or false,
    }
    if selected.pon or selected.host or selected.optical then
        local sample,availability=native.read_selected(provider,selected)
        if sample then
            local accepted,ingest_why=sampler.ingest_selected(state,sample)
            if not accepted then stop(ingest_why) end
            consecutive_failures=0
            if selected.pon then next_pon=sample.uptime+runtime.pon_interval_seconds end
            if selected.host then next_host=sample.uptime+runtime.host_interval_seconds end
            if selected.optical then
                next_optical=sample.uptime+runtime.optical_interval_seconds
            end
            local published,publish_why=snapshot.publish(owner,state)
            if not published then stop(publish_why) end
            if not publication then
                publication,publish_why=snapshot.admit()
                if not publication then stop(publish_why) end
            end
        else
            consecutive_failures=consecutive_failures+1
            io.stderr:write("aott-history: probe unavailable: "..tostring(availability).."\n")
            next_pon=now+math.min(runtime.pon_interval_seconds,60)
            next_host=now+math.min(runtime.host_interval_seconds,60)
            if runtime.optical_enabled then
                next_optical=now+math.min(runtime.optical_interval_seconds,60)
            end
            if consecutive_failures>=4 and publication then
                snapshot.revoke(publication)
                publication=nil
                snapshot.invalidate(owner)
            end
        end
    end
    local current=uptime() or now
    local due=math.min(next_pon,next_host,
        runtime.optical_enabled and next_optical or math.huge)
    local wait=math.max(1,math.min(5,due-current))
    local seconds=math.floor(wait)
    nixio.nanosleep(seconds,(wait-seconds)*1000000000)
end
