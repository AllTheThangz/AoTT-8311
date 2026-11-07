-- H-026: Strict H-016 JSON projection validation before cross-process use.
-- Pure Lua 5.1, no I/O, network, authentication or device interaction.
local M={}
local WINDOWS={
    hour=3600,day=86400,week=604800,
    month=2592000,ninety_days=7776000,
}
local ROOT={
    schema=true,kind=true,range=true,windows=true,
    samples=true,events=true,max_export_items=true,
    raw_sample_export_is_bounded=true,
    raw_event_export_is_bounded=true,
    source_only_not_live=true,
    raw_tail_independent_of_selected_range=true,
    history_is_volatile=true,
    actual_isp_uptime_unverified=true,
    optics_history_unavailable=true,
    rate_units=true,clock_domain=true,
    calendar_time_unverified=true,no_firmware_or_device_write=true,
}
local WINDOW_KEYS={
    rx=true,tx=true,window_complete=true,
    customer_wan_throughput_proven=true,
    full_internet_availability_proven=true,
    cross_reboot_continuity_proven=true,
    hardware_resource_qualified=true,
    requested_window_seconds=true,latest_uptime=true,
    earliest_sample_uptime=true,observed_span_seconds=true,
    samples_considered=true,samples_without_valid_rate=true,
    unavailable_pon_samples=true,unavailable_host_samples=true,
    excluded_cross_window_intervals=true,pon_state=true,
    host_link_speed_mbps=true,status=true,pon_observation=true,
    host_link_observation=true,
    terminated_at_epoch_boundary=true,history_exhausted=true,
}
local STATS={
    average_mbps=true,peak_mbps=true,covered_seconds=true,
    coverage_fraction=true,interval_count=true,
}
local SAMPLE={
    epoch_index=true,at_uptime=true,source=true,status=true,
    pon_state=true,host_link_speed_mbps=true,
    pon_observation=true,host_link_observation=true,
    elapsed_seconds=true,rx_mbps=true,tx_mbps=true,
}
local EVENT={
    epoch_index=true,at_uptime=true,kind=true,
    from=true,to=true,observation_window_seconds=true,channels=true,
}
local STATES={
    baseline=true,valid_interval=true,partial_interval=true,
    observation_unavailable=true,reboot=true,source_changed=true,
    sampling_gap=true,
}
local EVENTS={
    pon_state_change=true,host_link_change=true,reboot_observed=true,
    source_changed=true,sampling_gap=true,observation_unavailable=true,
}
local OBSERVED={observed=true,unavailable=true,not_sampled=true}
local STATUS={
    partial_measured_rates=true,no_valid_rate_intervals=true,
    no_retained_samples=true,
}
local function finite(value,lo,hi)
    return type(value)=="number" and value==value and
        value~=math.huge and value~=-math.huge and
        value>=lo and value<=hi
end
local function integer(value,lo,hi)
    return finite(value,lo,hi) and value==math.floor(value)
end
local function fields(value,allowed)
    if type(value)~="table" then return false end
    for name in pairs(value) do
        if not allowed[name] then return false end
    end
    return true
end
local function only_array(t,limit)
    if type(t)~="table" or #t>limit then return false end
    for key in pairs(t) do
        if not integer(key,1,#t) then return false end
    end
    return true
end
local function iface(value)
    return type(value)=="string" and #value<=15 and
        value:match("^[a-z][a-z0-9_.%-]*$") and
        (value:match("^eth%d+[%._]?%d*$") or
         value:match("^en[%w_.%-]+$") or
         value:match("^lan%d+$") or
         value:match("^sfp%d+$"))
end
local function optional_number(record,key,hi,integer_only)
    local value=record[key]
    if value==nil then return true end
    if integer_only then return integer(value,0,hi) end
    return finite(value,0,hi)
end
local function optional_enum(record,key,choices)
    return record[key]==nil or choices[record[key]]==true
end
local function stats_ok(x)
    if not fields(x,STATS) then return false end
    return optional_number(x,"average_mbps",1e12) and
        optional_number(x,"peak_mbps",1e12) and
        optional_number(x,"covered_seconds",7776000) and
        optional_number(x,"coverage_fraction",1) and
        optional_number(x,"interval_count",720,true)
end
local function window_ok(x,seconds)
    if not fields(x,WINDOW_KEYS) or
       x.requested_window_seconds~=seconds or
       x.window_complete~=false or
       x.customer_wan_throughput_proven~=false or
       x.full_internet_availability_proven~=false or
       x.cross_reboot_continuity_proven~=false or
       x.hardware_resource_qualified~=false or
       not stats_ok(x.rx) or not stats_ok(x.tx) then return false end
    if x.terminated_at_epoch_boundary~=nil and
       type(x.terminated_at_epoch_boundary)~="boolean" then return false end
    if x.history_exhausted~=nil and
       type(x.history_exhausted)~="boolean" then return false end
    if not optional_enum(x,"status",STATUS) or
       not optional_enum(x,"pon_observation",OBSERVED) or
       not optional_enum(x,"host_link_observation",OBSERVED) then
        return false
    end
    for key,maximum in pairs({
        latest_uptime=1e12,earliest_sample_uptime=1e12,
        observed_span_seconds=7776000,
        samples_considered=720,samples_without_valid_rate=720,
        unavailable_pon_samples=720,unavailable_host_samples=720,
        excluded_cross_window_intervals=720,
        pon_state=255,host_link_speed_mbps=100000,
    }) do
        if not optional_number(x,key,maximum,
            key~="latest_uptime" and key~="earliest_sample_uptime") then
            return false
        end
    end
    return true
end
local function sample_ok(x)
    if not fields(x,SAMPLE) or
       not integer(x.epoch_index,1,9007199254740990) or
       not finite(x.at_uptime,0,1e12) or
       not iface(x.source) or not STATES[x.status] or
       not optional_enum(x,"pon_observation",OBSERVED) or
       not optional_enum(x,"host_link_observation",OBSERVED) then
        return false
    end
    for key,limit in pairs({
        pon_state=255,host_link_speed_mbps=100000,
        elapsed_seconds=3600,rx_mbps=1e12,tx_mbps=1e12,
    }) do
        if not optional_number(x,key,limit,
            key=="pon_state" or key=="host_link_speed_mbps") then
            return false
        end
    end
    if x.rx_mbps~=nil or x.tx_mbps~=nil then
        if x.status~="valid_interval" or
           not finite(x.elapsed_seconds,0.001,3600) then return false end
    end
    return true
end
local function event_ok(x)
    if not fields(x,EVENT) or
       not integer(x.epoch_index,1,9007199254740990) or
       not finite(x.at_uptime,0,1e12) or
       not EVENTS[x.kind] then return false end
    if not optional_number(x,"from",100000,true) or
       not optional_number(x,"to",100000,true) or
       not optional_number(x,"observation_window_seconds",1e12) then
        return false
    end
    return optional_enum(x,"channels",{
        pon=true,host=true,["pon,host"]=true,
    })
end
function M.validate(data)
    local source_header=type(data)=="table" and
        data.kind=="aott_source_only_history" and data.source_only_not_live==true
    local live_header=type(data)=="table" and
        data.kind=="aott_local_history" and data.source_only_not_live==false
    if not fields(data,ROOT) or data.schema~=1 or
       (not source_header and not live_header) or
       data.max_export_items~=100 or
       data.history_is_volatile~=true or
       data.actual_isp_uptime_unverified~=true or
       data.optics_history_unavailable~=true or
       data.raw_sample_export_is_bounded~=true or
       data.raw_event_export_is_bounded~=true or
       data.raw_tail_independent_of_selected_range~=true or
       data.calendar_time_unverified~=true or
       data.no_firmware_or_device_write~=true or
       data.rate_units~="Mbps" or
       data.clock_domain~="onu_monotonic_uptime" or
       not WINDOWS[data.range] then
        return nil,"invalid_projection_header"
    end
    if type(data.windows)~="table" then
        return nil,"invalid_projection_windows"
    end
    for key in pairs(data.windows) do
        if not WINDOWS[key] then return nil,"unexpected_history_window" end
    end
    for key,duration in pairs(WINDOWS) do
        if not window_ok(data.windows[key],duration) then
            return nil,"invalid_history_window"
        end
    end
    if not only_array(data.samples,100) or
       not only_array(data.events,100) then
        return nil,"invalid_history_arrays"
    end
    for _,entry in ipairs(data.samples) do
        if not sample_ok(entry) then return nil,"invalid_history_sample" end
    end
    for _,entry in ipairs(data.events) do
        if not event_ok(entry) then return nil,"invalid_history_event" end
    end
    return true
end
M.MAX_BYTES=65536
return M
