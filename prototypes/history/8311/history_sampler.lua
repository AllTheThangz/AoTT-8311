-- AoTT-8311 H-011: bounded, RAM-only observation core.
-- Pure Lua 5.1, no timers, processes, filesystem, network, flash or startup hook.
-- A future board-qualified collector must provide monotonic observations.
local math_model = require "8311.history_model"
local M = {}

local DEFAULT_SAMPLES, MAX_SAMPLES = 120, 720
local DEFAULT_EVENTS, MAX_EVENTS = 128, 256
local MAX_GAP_SECONDS = 3600
local MAX_EXPORT_ITEMS = 100

local function integer(v, a, b)
    return type(v) == "number" and v == v and
        v ~= math.huge and v ~= -math.huge and
        v == math.floor(v) and v >= a and v <= b
end

local function valid_uptime(v)
    return type(v) == "number" and v == v and
        v ~= math.huge and v ~= -math.huge and v >= 0 and v <= 1e12
end

local function token(v, limit)
    return type(v) == "string" and #v > 0 and #v <= limit and
        v:match("^[%w_.:%-]+$") ~= nil
end

-- Accept only host-facing Linux interface name families, not arbitrary
-- identifiers that might be a PON serial, LOID, URL or MAC address.
-- Future board adapters must extend this allowlist after qualification.
local function host_interface(v)
    if not token(v, 15) or not v:match("^[a-z][a-z0-9_.%-]*$") then
        return false
    end
    return v:match("^eth%d+[%._]?%d*$")~=nil or
           v:match("^en[%w_.%-]+$")~=nil or
           v:match("^lan%d+$")~=nil or
           v:match("^sfp%d+$")~=nil
end

local function byte_counter(v)
    if v == nil then return nil end
    if type(v) == "number" then
        -- The counter model itself rejects inexact Lua floating-point values.
        if v ~= v or v < 0 or v > 9007199254740991 or
            v ~= math.floor(v) then return nil end
        return string.format("%.0f", v)
    end
    if type(v) ~= "string" or #v < 1 or #v > 20 or
        not v:match("^%d+$") then return nil end
    return v
end

local function clean(sample)
    if type(sample) ~= "table" or not token(sample.boot, 80) or
       not host_interface(sample.source) or not valid_uptime(sample.uptime) then
        return nil, "invalid_sample_identity_or_time"
    end
    -- Strict whitelist: discard every unrelated value, including subscriber
    -- serials, LOID, auth tokens, URLs, MAC addresses and raw device output.
    local value = {
        boot=sample.boot, uptime=sample.uptime, source=sample.source,
    }
    if integer(sample.pon_state, 0, 255) then
        value.pon_state=sample.pon_state
    end
    if integer(sample.ethernet_mbps, 0, 100000) then
        value.ethernet_mbps=sample.ethernet_mbps
    end
    local counters=type(sample.eth)=="table" and sample.eth or {}
    value.eth={
        RxGoodBytes=byte_counter(counters.RxGoodBytes),
        TxGoodBytes=byte_counter(counters.TxGoodBytes),
    }
    return value
end

local function capacity(v, default, lower, upper)
    if v == nil then return default end
    if not integer(v, lower, upper) then return nil end
    return v
end

function M.new(options)
    if options ~= nil and type(options) ~= "table" then
        return nil, "invalid_options"
    end
    options = options or {}
    local max_samples=capacity(options.max_samples,DEFAULT_SAMPLES,2,MAX_SAMPLES)
    local max_events=capacity(options.max_events,DEFAULT_EVENTS,2,MAX_EVENTS)
    if not max_samples or not max_events then return nil, "invalid_capacity" end
    return {
        schema=1, max_samples=max_samples, max_events=max_events,
        samples={}, samples_head=1, samples_count=0,
        events={}, events_head=1, events_count=0,
        last_seen=nil, previous=nil, accepted=0,
        pon_previous=nil, host_previous=nil,
    }
end

-- Bounded O(1) ring insert, oldest item evicted upon reaching capacity.
local function insert(buffer, record, head_name, count_name, max_name, state)
    local count, head=state[count_name],state[head_name]
    local cap=state[max_name]
    if count < cap then
        buffer[((head + count - 1) % cap) + 1] = record
        state[count_name] = count + 1
    else
        buffer[head] = record
        state[head_name] = (head % cap) + 1
    end
end

local function put_sample(state, value)
    insert(state.samples,value,"samples_head","samples_count","max_samples",state)
end
local function put_event(state, value)
    insert(state.events,value,"events_head","events_count","max_events",state)
end
local function event(state, kind, sample, more)
    local value={
        kind=kind,
        at_uptime=sample.uptime,
        walltime_trust="unknown",
    }
    if more then
        for k,v in pairs(more) do value[k]=v end
    end
    put_event(state,value)
end

-- Returns only one-word state and counts. No boot, identity or raw counter.
function M.ingest(state, input)
    if type(state)~="table" or state.schema~=1 or
       type(state.samples)~="table" or type(state.events)~="table" then
        return nil, "invalid_state"
    end
    local current, why=clean(input)
    if not current then return nil, why end
    local last=state.last_seen
    if last and current.boot==last.boot and current.uptime<=last.uptime then
        return nil,"nonmonotonic_observation"
    end

    local valid_pon=current.pon_state~=nil
    local valid_host=current.ethernet_mbps~=nil
    local valid_status=valid_pon and valid_host
    local status, new_events, rates, rate_error="baseline",0,nil,nil
    local prev=state.previous
    local function emit(kind, details)
        event(state,kind,current,details)
        new_events=new_events+1
    end

    if last and last.boot~=current.boot then
        emit("reboot_observed")
        status="reboot"
        prev=nil
    elseif last and last.source~=current.source then
        emit("source_changed")
        status="source_changed"
        prev=nil
    elseif last and current.uptime-last.uptime>MAX_GAP_SECONDS then
        emit("sampling_gap",{observation_window_seconds=current.uptime-last.uptime})
        status="sampling_gap"
        prev=nil
    end

    -- PON and host-link status have independent freshness. If the PON
    -- command fails while host-link status changes (or vice versa), keep
    -- the channel that was actually observed. Never map nil to a down
    -- state or compare through a missing reading.
    if status~="baseline" then
        state.pon_previous=nil
        state.host_previous=nil
    end
    local function observe_channel(previous, value, kind)
        if value==nil then return nil end
        if previous and previous.boot==current.boot and
           previous.source==current.source then
            local elapsed=current.uptime-previous.uptime
            if elapsed>0 and elapsed<=MAX_GAP_SECONDS and
               value~=previous.value then
                emit(kind,{
                    from=previous.value,
                    to=value,
                    observation_window_seconds=elapsed,
                })
            end
        end
        return {
            boot=current.boot,source=current.source,
            uptime=current.uptime,value=value,
        }
    end
    local next_pon=observe_channel(
        state.pon_previous,current.pon_state,"pon_state_change")
    local next_host=observe_channel(
        state.host_previous,current.ethernet_mbps,"host_link_change")

    if not valid_status then
        if status=="baseline" then status="observation_unavailable" end
        emit("observation_unavailable",{
            channels=not valid_pon and (not valid_host and "pon,host" or "pon")
                     or "host",
        })
        state.previous=nil
    elseif prev and status=="baseline" then
        local elapsed=current.uptime-prev.uptime
        if elapsed<=0 or elapsed>MAX_GAP_SECONDS then
            emit("sampling_gap",{observation_window_seconds=elapsed})
            status="sampling_gap"
        else
            rates,rate_error=math_model.eth_rates(prev,current)
            status="valid_interval"
        end
        state.previous=current
    else
        state.previous=current
    end
    state.pon_previous=next_pon
    state.host_previous=next_host

    -- These records never store boot identifier or raw byte counters.
    local summary={
        at_uptime=current.uptime,
        source=current.source,
        pon_state=current.pon_state,
        ethernet_mbps=current.ethernet_mbps,
        pon_observation=valid_pon and "observed" or "unavailable",
        host_link_observation=valid_host and "observed" or "unavailable",
        status=status,
        walltime_trust="unknown",
    }
    if rates then
        summary.elapsed_seconds=rates.elapsed_seconds
        summary.rx_mbps=rates.rx_mbps
        summary.tx_mbps=rates.tx_mbps
        summary.rx_unavailable=rates.rx_mbps_unavailable
        summary.tx_unavailable=rates.tx_mbps_unavailable
        summary.rate_source=rates.source
        summary.direction=rates.direction
    else
        summary.rate_unavailable= status=="valid_interval" and
            (rate_error or "no_valid_counter_pairs") or "no_comparable_interval"
    end
    put_sample(state,summary)
    state.last_seen={boot=current.boot,uptime=current.uptime,source=current.source}
    state.accepted=state.accepted+1
    return {
        status=status,events_added=new_events,
        samples_retained=state.samples_count,
        events_retained=state.events_count,
        has_rate=rates~=nil,
    }
end

local function copy_record(src)
    local copy={}
    for k,v in pairs(src) do
        if type(v)=="string" or type(v)=="number" or type(v)=="boolean" then
            copy[k]=v
        end
    end
    return copy
end

-- Bounded query, newest observations returned in chronological order.
function M.recent(state, which, limit)
    if type(state)~="table" or state.schema~=1 then return nil,"invalid_state" end
    if which~="samples" and which~="events" then return nil,"unknown_collection" end
    limit=limit or 24
    if not integer(limit,1,MAX_EXPORT_ITEMS) then return nil,"invalid_query_limit" end
    local count,head,cap=state[which.."_count"],state[which.."_head"],
        state["max_"..which]
    local values=state[which]
    if not integer(count,0,cap) or not integer(head,1,cap) or
       type(values)~="table" then return nil,"corrupt_state" end
    local results={}
    for offset=math.max(0,count-limit),count-1 do
        local index=((head+offset-1)%cap)+1
        if type(values[index])~="table" then return nil,"corrupt_state" end
        results[#results+1]=copy_record(values[index])
    end
    return results
end

return M
