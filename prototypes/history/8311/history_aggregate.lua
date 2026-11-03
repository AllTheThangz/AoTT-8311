-- H-013/H-014: read-only windowed rate aggregates over bounded H-011 RAM.
-- No native commands, timers, filesystem, network calls or flash writes.
-- All rates are host-interface Ethernet statistics, not customer WAN speed.
local M = {}
local MAX_SAMPLES = 720
local MAX_WINDOW_SECONDS = 90 * 86400
local MAX_INTERVAL_SECONDS = 3600
local BOUNDARIES = {reboot=true,source_changed=true,sampling_gap=true}
local STATUSES = {
    baseline=true,valid_interval=true,observation_unavailable=true,
    reboot=true,source_changed=true,sampling_gap=true,
}
local function integer(v, minimum, maximum)
    return type(v) == "number" and v == v and v ~= math.huge and
           v ~= -math.huge and v == math.floor(v) and
           v >= minimum and v <= maximum
end
local function finite(v, minimum, maximum)
    return type(v) == "number" and v == v and v ~= math.huge and
           v ~= -math.huge and v >= minimum and v <= maximum
end
local function source(v)
    if type(v) ~= "string" or #v == 0 or #v > 15 or
       not v:match("^[a-z][a-z0-9_.%-]*$") then return false end
    return v:match("^eth%d+[%._]?%d*$")~=nil or
           v:match("^en[%w_.%-]+$")~=nil or
           v:match("^lan%d+$")~=nil or
           v:match("^sfp%d+$")~=nil
end
local function reset()
    return {weighted_sum=0,covered_seconds=0,interval_count=0,
            peak_mbps=nil,average_mbps=nil}
end
local function valid_ring(state)
    if type(state) ~= "table" or state.schema ~= 1 or
       type(state.samples) ~= "table" or
       not integer(state.max_samples,2,MAX_SAMPLES) or
       not integer(state.samples_head,1,state.max_samples) or
       not integer(state.samples_count,0,state.max_samples) then
        return nil,"invalid_bounded_history"
    end
    return true
end
local function at(state,offset)
    local index = ((state.samples_head+offset-1)%state.max_samples)+1
    local record=state.samples[index]
    if type(record) ~= "table" or
       not finite(record.at_uptime,0,1e12) or
       not source(record.source) or
       not STATUSES[record.status] or
       (record.pon_state~=nil and not integer(record.pon_state,0,255)) or
       (record.ethernet_mbps~=nil and not integer(record.ethernet_mbps,0,100000)) or
       (record.pon_observation~=nil and
        record.pon_observation~="observed" and
        record.pon_observation~="unavailable") or
       (record.host_link_observation~=nil and
        record.host_link_observation~="observed" and
        record.host_link_observation~="unavailable") then
        return nil
    end
    return record
end
local function track(channel,value,elapsed)
    if value==nil then return end
    channel.weighted_sum=channel.weighted_sum+(value*elapsed)
    channel.covered_seconds=channel.covered_seconds+elapsed
    channel.interval_count=channel.interval_count+1
    channel.peak_mbps=channel.peak_mbps and
        math.max(channel.peak_mbps,value) or value
end
local function finish(channel,requested)
    if channel.covered_seconds>0 then
        channel.average_mbps=channel.weighted_sum/channel.covered_seconds
    end
    channel.coverage_fraction=math.min(1,channel.covered_seconds/requested)
    channel.weighted_sum=nil
    return channel
end

-- Window is requested seconds relative to the latest retained uptime,
-- not a calendar timestamp. Never reconstruct missing or pre-reboot time.
-- A rate interval that crosses the window boundary is entirely excluded
-- rather than assuming constant traffic inside a partial interval.
function M.summarize(state,window_seconds)
    local ok,why=valid_ring(state)
    if not ok then return nil,why end
    if window_seconds==nil then window_seconds=3600 end
    if not integer(window_seconds,1,MAX_WINDOW_SECONDS) then
        return nil,"invalid_rate_window"
    end
    local result={
        schema=1,requested_window_seconds=window_seconds,
        time_basis="onu_monotonic_uptime",
        window_complete=false,
        latest_uptime=nil,earliest_sample_uptime=nil,
        observed_span_seconds=0,samples_considered=0,
        unavailable_pon_samples=0,unavailable_host_samples=0,
        samples_without_valid_rate=0,
        excluded_cross_window_intervals=0,
        terminated_at_epoch_boundary=false,
        history_exhausted=false,
        rx=reset(),tx=reset(),
        rate_source="host_ethernet_byte_counters",
        customer_wan_throughput_proven=false,
        full_internet_availability_proven=false,
        cross_reboot_continuity_proven=false,
        hardware_resource_qualified=false,
        no_device_write=true,
    }
    if state.samples_count==0 then
        result.status="no_retained_samples"
        finish(result.rx,window_seconds)
        finish(result.tx,window_seconds)
        return result
    end

    local newest=at(state,state.samples_count-1)
    if not newest then return nil,"corrupt_history_sample" end
    local end_time=newest.at_uptime
    local cutoff=math.max(0,end_time-window_seconds)
    result.latest_uptime=end_time
    result.oldest_relevant_uptime=cutoff
    result.source=newest.source
    result.pon_state=newest.pon_state
    result.host_link_speed_mbps=newest.ethernet_mbps
    result.pon_observation=newest.pon_observation or "unavailable"
    result.host_link_observation=newest.host_link_observation or "unavailable"
    local previous_time=nil
    local stopped_for_cutoff=false
    for i=state.samples_count-1,0,-1 do
        local record=at(state,i)
        if not record then return nil,"corrupt_history_sample" end
        local when=record.at_uptime
        if record.source~=newest.source then
            -- Even malformed history with an omitted source marker
            -- cannot join unrelated Ethernet interfaces.
            result.terminated_at_epoch_boundary=true
            break
        end
        if previous_time~=nil and when>=previous_time then
            return nil,"corrupt_nonmonotonic_history"
        end
        if when<cutoff then
            stopped_for_cutoff=true
            break
        end
        previous_time=when
        result.samples_considered=result.samples_considered+1
        result.earliest_sample_uptime=when

        if record.pon_observation~="observed" then
            result.unavailable_pon_samples=
                result.unavailable_pon_samples+1
        end
        if record.host_link_observation~="observed" then
            result.unavailable_host_samples=
                result.unavailable_host_samples+1
        end
        local elapsed=record.elapsed_seconds
        local rx=record.rx_mbps
        local tx=record.tx_mbps
        local included=false
        if elapsed~=nil then
            if not finite(elapsed,0,MAX_INTERVAL_SECONDS) or elapsed==0
               or record.status~="valid_interval" or
               record.rate_source~="hardware_ethernet_byte_counters" or
               record.direction~="host_interface_rx_tx" or
               (rx~=nil and not finite(rx,0,1e12)) or
               (tx~=nil and not finite(tx,0,1e12)) or
               (rx==nil and tx==nil) then
                return nil,"corrupt_rate_interval"
            end
            if when-elapsed >= cutoff then
                track(result.rx,rx,elapsed)
                track(result.tx,tx,elapsed)
                included=true
            else
                result.excluded_cross_window_intervals=
                    result.excluded_cross_window_intervals+1
            end
        elseif rx~=nil or tx~=nil then
            return nil,"rate_without_interval"
        end
        if not included then
            result.samples_without_valid_rate=
                result.samples_without_valid_rate+1
        end
        if BOUNDARIES[record.status] then
            result.terminated_at_epoch_boundary=true
            break
        end
    end

    if result.earliest_sample_uptime~=nil then
        result.observed_span_seconds=end_time-result.earliest_sample_uptime
    end
    -- We can never assert complete measurement for a requested calendar
    -- window solely because some rate data is present.
    result.history_exhausted=not stopped_for_cutoff
    finish(result.rx,window_seconds)
    finish(result.tx,window_seconds)
    result.status=result.rx.interval_count+result.tx.interval_count>0
        and "partial_measured_rates" or "no_valid_rate_intervals"
    return result
end

-- Bounded five-window source for future history views. The 24-hour,
-- 7-day, 30-day and 90-day panels are allowed queries, NOT promises of
-- that much retained data or Internet availability.
local PRESETS={
    {"hour",3600},
    {"day",86400},
    {"week",7*86400},
    {"month",30*86400},
    {"ninety_days",90*86400},
}
function M.presets(state)
    local results={schema=1}
    for _,choice in ipairs(PRESETS) do
        local window,reason=M.summarize(state,choice[2])
        if not window then return nil,reason end
        results[choice[1]]=window
    end
    return results
end

return M
