-- H-016: source-only bounded history projection and JSON/CSV export.
-- No device I/O, file writes, network probes, timers or HTTP endpoints.
local sampler=require "8311.history_sampler"
local M={}
local MAX_RAW=100
local MAX_EXPORT_BYTES=65536
local MAX_EPOCH=9007199254740990
local RANGES={"hour","day","week","month","ninety_days"}
local SAMPLE_STATES={
    baseline=true,valid_interval=true,observation_unavailable=true,
    reboot=true,source_changed=true,sampling_gap=true,
}
local EVENTS={
    pon_state_change=true,host_link_change=true,reboot_observed=true,
    source_changed=true,sampling_gap=true,observation_unavailable=true,
}
local MISSING={observed=true,unavailable=true}
local function finite(x,low,high)
    return type(x)=="number" and x==x and x~=math.huge and
        x~=-math.huge and x>=low and x<=high
end
local function int(x,low,high)
    return finite(x,low,high) and x==math.floor(x)
end
local function interface(s)
    if type(s)~="string" or #s==0 or #s>15 or
       not s:match("^[a-z][a-z0-9_.%-]*$") then return false end
    return s:match("^eth%d+[%._]?%d*$")~=nil or
           s:match("^en[%w_.%-]+$")~=nil or
           s:match("^lan%d+$")~=nil or
           s:match("^sfp%d+$")~=nil
end
local function num(out,key,value,max)
    if finite(value,0,max) then out[key]=value end
end
local function count(out,key,value,max)
    if int(value,0,max) then out[key]=value end
end
local function flag(out,key,value)
    if type(value)=="boolean" then out[key]=value end
end
local function label(out,key,value,allow)
    if allow[value] then out[key]=value end
end
local function stats(row)
    local out={}
    if type(row)~="table" then return out end
    num(out,"average_mbps",row.average_mbps,1e12)
    num(out,"peak_mbps",row.peak_mbps,1e12)
    num(out,"covered_seconds",row.covered_seconds,90*86400)
    num(out,"coverage_fraction",row.coverage_fraction,1)
    count(out,"interval_count",row.interval_count,720)
    return out
end
local function window(raw)
    local out={
        rx=stats(raw.rx),tx=stats(raw.tx),
        window_complete=false,
        customer_wan_throughput_proven=false,
        full_internet_availability_proven=false,
        cross_reboot_continuity_proven=false,
        hardware_resource_qualified=false,
    }
    local numeric={
        requested_window_seconds=90*86400,
        latest_uptime=1e12,earliest_sample_uptime=1e12,
        observed_span_seconds=90*86400,
        samples_considered=720,
        samples_without_valid_rate=720,
        unavailable_pon_samples=720,
        unavailable_host_samples=720,
        excluded_cross_window_intervals=720,
        pon_state=255,host_link_speed_mbps=100000,
    }
    for key,max in pairs(numeric) do
        if key=="latest_uptime" or key=="earliest_sample_uptime" then
            num(out,key,raw[key],max)
        else
            count(out,key,raw[key],max)
        end
    end
    local statuses={
        partial_measured_rates=true,no_valid_rate_intervals=true,
        no_retained_samples=true,
    }
    label(out,"status",raw.status,statuses)
    label(out,"pon_observation",raw.pon_observation,MISSING)
    label(out,"host_link_observation",raw.host_link_observation,MISSING)
    flag(out,"terminated_at_epoch_boundary",raw.terminated_at_epoch_boundary)
    flag(out,"history_exhausted",raw.history_exhausted)
    return out
end
local function sample(raw,cutoff)
    if type(raw)~="table" or not int(raw.epoch_index,1,MAX_EPOCH)
       or not finite(raw.at_uptime,0,1e12) or not interface(raw.source)
       or not SAMPLE_STATES[raw.status] then return nil end
    local row={
        epoch_index=raw.epoch_index,at_uptime=raw.at_uptime,
        source=raw.source,status=raw.status,
    }
    count(row,"pon_state",raw.pon_state,255)
    count(row,"host_link_speed_mbps",raw.ethernet_mbps,100000)
    label(row,"pon_observation",raw.pon_observation,MISSING)
    label(row,"host_link_observation",raw.host_link_observation,MISSING)
    -- If an interval reaches outside the requested display window,
    -- remove both rates. The displayed aggregate uses the same rule.
    if finite(raw.elapsed_seconds,0,3600) and raw.elapsed_seconds>0
       and raw.at_uptime-raw.elapsed_seconds>=cutoff and
       raw.status=="valid_interval" and
       raw.rate_source=="hardware_ethernet_byte_counters" and
       raw.direction=="host_interface_rx_tx" then
        num(row,"elapsed_seconds",raw.elapsed_seconds,3600)
        num(row,"rx_mbps",raw.rx_mbps,1e12)
        num(row,"tx_mbps",raw.tx_mbps,1e12)
    end
    return row
end
local function event(raw)
    if type(raw)~="table" or not int(raw.epoch_index,1,MAX_EPOCH)
       or not finite(raw.at_uptime,0,1e12) or
       not EVENTS[raw.kind] then return nil end
    local row={
        epoch_index=raw.epoch_index,
        at_uptime=raw.at_uptime,kind=raw.kind,
    }
    count(row,"from",raw.from,100000)
    count(row,"to",raw.to,100000)
    num(row,"observation_window_seconds",
        raw.observation_window_seconds,1e12)
    label(row,"channels",raw.channels,{
        pon=true,host=true,["pon,host"]=true,
    })
    return row
end

-- No raw device output or boot ID is copied to public data.
-- Only events matching the newest private epoch can be displayed, so a
-- reboot resetting uptime can never make old events appear new.
function M.project(state,range,limit)
    range=range or "hour"
    limit=limit or 100
    if not int(limit,1,MAX_RAW) then return nil,"invalid_export_limit" end
    local allowed=false
    for _,name in ipairs(RANGES) do
        if name==range then allowed=true end
    end
    if not allowed then return nil,"invalid_export_range" end
    if type(state)~="table" or not int(state.epoch_index,1,MAX_EPOCH) then
        return nil,"invalid_export_state"
    end
    local histories,why=sampler.history_windows(state)
    if not histories then return nil,why end
    local selected=histories[range]
    if type(selected)~="table" then return nil,"missing_window" end
    local latest=selected.latest_uptime
    -- Exports include up to 100 latest-epoch records independent of the
    -- initially selected panel. Each UI/CSV range applies its own cutoff.
    local raw_samples,err=sampler.recent(state,"samples",limit)
    if not raw_samples then return nil,err end
    local raw_events,error_code=sampler.recent(state,"events",limit)
    if not raw_events then return nil,error_code end
    local samples,events={},{}
    for _,value in ipairs(raw_samples) do
        if value.epoch_index==state.epoch_index and
           finite(value.at_uptime,0,latest or 1e12) then
            local safe=sample(value,0)
            if not safe then return nil,"invalid_export_sample" end
            samples[#samples+1]=safe
        end
    end
    for _,value in ipairs(raw_events) do
        if value.epoch_index==state.epoch_index and
           finite(value.at_uptime,0,latest or 1e12) then
            local safe=event(value)
            if not safe then return nil,"invalid_export_event" end
            events[#events+1]=safe
        end
    end
    local windows={}
    for _,name in ipairs(RANGES) do
        local v=histories[name]
        if type(v)~="table" then return nil,"invalid_window" end
        windows[name]=window(v)
    end
    return {
        schema=1,kind="aott_source_only_history",
        range=range,
        windows=windows,samples=samples,events=events,
        max_export_items=MAX_RAW,
        raw_sample_export_is_bounded=true,
        raw_event_export_is_bounded=true,
        source_only_not_live=true,
        raw_tail_independent_of_selected_range=true,
        history_is_volatile=true,
        actual_isp_uptime_unverified=true,
        optics_history_unavailable=true,
        rate_units="Mbps",
        clock_domain="onu_monotonic_uptime",
        calendar_time_unverified=true,
        no_firmware_or_device_write=true,
    }
end

local function escape_json(value)
    -- \u00XX escaping also removes markup delimiters so exported data is
    -- safe to embed into a non-executable text area, not a script tag.
    return '"' .. value:gsub('[%z\1-\31\\\"<>&]',function(char)
        local ascii=char:byte()
        if char=="\\" then return "\\\\" end
        if char=='"' then return '\\"' end
        return string.format("\\u%04x",ascii)
    end) .. '"'
end
local function encode(value,depth,force_array)
    if depth>12 then return nil,"json_depth_exceeded" end
    local t=type(value)
    if t=="string" then return escape_json(value) end
    if t=="number" then
        if not finite(value,-1e15,1e15) then return nil,"invalid_json_number" end
        return string.format("%.15g",value)
    end
    if t=="boolean" then return value and "true" or "false" end
    if t~="table" then return nil,"invalid_json_type" end
    local entries={}
    if force_array then
        for key in pairs(value) do
            if not int(key,1,MAX_RAW) then return nil,"invalid_json_array" end
        end
        for i=1,#value do
            local child,why=encode(value[i],depth+1,false)
            if not child then return nil,why end
            entries[#entries+1]=child
        end
        return "["..table.concat(entries,",").."]"
    end
    local keys={}
    for key in pairs(value) do
        if type(key)~="string" or #key>64 then
            return nil,"invalid_json_key"
        end
        keys[#keys+1]=key
    end
    table.sort(keys)
    for _,key in ipairs(keys) do
        local child,why=encode(value[key],depth+1,
                               key=="events" or key=="samples")
        if not child then return nil,why end
        entries[#entries+1]=escape_json(key)..":"..child
    end
    return "{"..table.concat(entries,",").."}"
end
function M.export_json(state,range,limit)
    local projection,why=M.project(state,range,limit)
    if not projection then return nil,why end
    local encoded,err=encode(projection,0,false)
    if not encoded then return nil,err end
    if #encoded>MAX_EXPORT_BYTES then return nil,"export_too_large" end
    return encoded
end

-- Fixed CSV columns. All data must pass the same projector first.
-- Prefix spreadsheet formula-looking string values, even though only
-- whitelisted names and statuses are currently accepted by the projector.
local CSV_COLUMNS={
    "record_type","at_uptime","source","status",
    "pon_state","host_link_speed_mbps","rx_mbps","tx_mbps",
    "event_kind","from","to","observation_window_seconds",
}
local function cell(value)
    if value==nil then return "" end
    local v=tostring(value)
    if #v>80 then return nil,"csv_cell_too_long" end
    if v:match("^[=+%-@]") and type(value)=="string" then
        v="'"..v
    end
    v=v:gsub('"','""')
    return '"'..v..'"'
end
local function row(values)
    local fields={}
    for i=1,#CSV_COLUMNS do
        local output,why=cell(values[i])
        if not output then return nil,why end
        fields[#fields+1]=output
    end
    return table.concat(fields,",")
end
function M.export_csv(state,range,limit)
    local projection,why=M.project(state,range,limit)
    if not projection then return nil,why end
    local lines={table.concat(CSV_COLUMNS,",")}
    local selected=projection.windows[projection.range]
    local cutoff=selected.latest_uptime and
        math.max(0,selected.latest_uptime-selected.requested_window_seconds)
        or 0
    for _,entry in ipairs(projection.samples) do
        if entry.at_uptime>=cutoff then
            local eligible=entry.elapsed_seconds and
                entry.at_uptime-entry.elapsed_seconds>=cutoff
            local csv,err=row({"sample",entry.at_uptime,entry.source,
                entry.status,entry.pon_state,entry.host_link_speed_mbps,
                eligible and entry.rx_mbps or nil,
                eligible and entry.tx_mbps or nil,
                "","","",""})
            if not csv then return nil,err end
            lines[#lines+1]=csv
        end
    end
    for _,entry in ipairs(projection.events) do
        if entry.at_uptime>=cutoff then
            local csv,err=row({"event",entry.at_uptime,"","",nil,nil,
                nil,nil,entry.kind,entry.from,entry.to,
                entry.observation_window_seconds})
            if not csv then return nil,err end
            lines[#lines+1]=csv
        end
    end
    local result=table.concat(lines,"\r\n").."\r\n"
    if #result>MAX_EXPORT_BYTES then return nil,"export_too_large" end
    return result
end
return M
