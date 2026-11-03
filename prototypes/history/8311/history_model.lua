-- AoTT-8311 vNext: portable, dependency-free historical observation math.
-- No I/O, device changes, environment access, filesystem writes or timers.
-- This is an offline source model, not an installed monitoring service.
local M = {}
local MAX_U64 = "18446744073709551615"
local MAX_SAFE_EXACT = "9007199254740991" -- 2^53 - 1
local MAX_INTERVAL = 3600
local MAX_EVENT_COUNT = 2048

local function dec_compare(a, b)
    if #a ~= #b then return #a < #b and -1 or 1 end
    if a == b then return 0 end
    return a < b and -1 or 1
end

local function normalize_unsigned(value)
    if type(value) ~= "string" then
        -- Lua 5.1 doubles cannot represent all 64-bit counter values.
        -- Accept numeric samples only in the exactly representable range.
        if type(value) ~= "number" or value ~= value or
           value == math.huge or value < 0 or value > 9007199254740991 or
           math.floor(value) ~= value then return nil end
        value = string.format("%.0f", value)
    end
    if not value:match("^(%d+)$") or #value > 20 then return nil end
    local digits = value:gsub("^0+", "")
    if digits == "" then digits = "0" end
    if dec_compare(digits, MAX_U64) > 0 then return nil end
    return digits
end

-- Unsigned 64-bit decimal subtraction without conversion to floating point.
-- Never invent a wrap: a counter regression requires a fresh baseline.
function M.counter_delta(prior, current)
    local a = normalize_unsigned(prior)
    local b = normalize_unsigned(current)
    if not a or not b then return nil, "invalid_counter" end
    if dec_compare(b, a) < 0 then return nil, "counter_reset_or_wrap" end
    local carry, result = 0, {}
    for i = 0, math.max(#a, #b) - 1 do
        local pos_a = #a - i
        local pos_b = #b - i
        local left = pos_b > 0 and tonumber(b:sub(pos_b, pos_b)) or 0
        local right = pos_a > 0 and tonumber(a:sub(pos_a, pos_a)) or 0
        local diff = left - right - carry
        if diff < 0 then diff, carry = diff + 10, 1
        else carry = 0 end
        result[#result + 1] = tostring(diff)
    end
    if carry ~= 0 then return nil, "counter_reset_or_wrap" end
    local digits = {}
    for i = #result, 1, -1 do digits[#digits + 1] = result[i] end
    local answer = table.concat(digits):gsub("^0+", "")
    return answer ~= "" and answer or "0"
end

local function bounded_time(value)
    return type(value) == "number" and value == value and
           value ~= math.huge and value ~= -math.huge and
           value >= 0 and value <= 1e12
end

local function interval(prior, current)
    if type(prior) ~= "table" or type(current) ~= "table" or
       type(prior.boot) ~= "string" or prior.boot == "" or
       current.boot ~= prior.boot then return nil, "reboot_or_unknown_boot" end
    if not bounded_time(prior.uptime) or
       not bounded_time(current.uptime) then return nil, "invalid_uptime" end
    local seconds = current.uptime - prior.uptime
    if seconds <= 0 or seconds > MAX_INTERVAL then
        return nil, "invalid_sampling_interval"
    end
    return seconds
end

-- Speeds are host-facing RX and TX; they are not a subscriber speed test.
-- Missing counters remain absent, never zero-filled.
function M.eth_rates(previous, current)
    local elapsed, why = interval(previous, current)
    if not elapsed then return nil, why end
    local a, b = previous.eth or {}, current.eth or {}
    local result = {
        elapsed_seconds = elapsed,
        direction = "host_interface_rx_tx",
        source = "hardware_ethernet_byte_counters",
    }
    for _, item in ipairs({
        {"RxGoodBytes", "rx_mbps"},
        {"TxGoodBytes", "tx_mbps"},
    }) do
        local digits, error_code = M.counter_delta(a[item[1]], b[item[1]])
        if not digits then
            result[item[2] .. "_unavailable"] = error_code
        elseif dec_compare(digits, MAX_SAFE_EXACT) > 0 then
            result[item[2] .. "_unavailable"] = "unrepresentable_delta"
        else
            local bytes = tonumber(digits)
            result[item[2]] = (bytes * 8) / (elapsed * 1000000)
        end
    end
    if result.rx_mbps == nil and result.tx_mbps == nil then
        return nil, "no_valid_counter_pairs"
    end
    return result
end

local function valid_pon(value)
    return type(value) == "number" and value == math.floor(value) and
           value >= 0 and value <= 255
end

local function valid_speed(value)
    return type(value) == "number" and value == math.floor(value) and
           value >= 0 and value <= 100000
end

local function push_bounded(events, event, limit)
    local list = {}
    local start = math.max(1, #events - limit + 2)
    for i = start, #events do
        list[#list + 1] = events[i]
    end
    list[#list + 1] = event
    return list
end

-- Calculate only observed changes. No claims about WAN/IP connectivity.
-- A sampled transition time bounds the true event between samples.
function M.observe_transition(previous, current, events, limit)
    if type(current) ~= "table" or type(current.boot) ~= "string" or
       current.boot == "" or not bounded_time(current.uptime) or
       not valid_pon(current.pon_state) or
       not valid_speed(current.ethernet_mbps) then
        return nil, "invalid_observation"
    end
    if type(events) ~= "table" then events = {} end
    limit = limit or 256
    if type(limit) ~= "number" or limit ~= math.floor(limit) or
       limit < 1 or limit > MAX_EVENT_COUNT or #events > MAX_EVENT_COUNT then
        return nil, "invalid_event_limit"
    end
    if previous == nil then return events, "initial_baseline" end
    if type(previous) ~= "table" or type(previous.boot) ~= "string" or
       not bounded_time(previous.uptime) or
       not valid_pon(previous.pon_state) or
       not valid_speed(previous.ethernet_mbps) then
        return nil, "invalid_previous_observation"
    end
    if previous.boot ~= current.boot then
        return push_bounded(events, {
            kind = "reboot_observed",
            at_uptime = current.uptime,
            walltime_trust = "unknown",
        }, limit), "reboot"
    end
    local elapsed = current.uptime - previous.uptime
    if elapsed <= 0 or elapsed > MAX_INTERVAL then
        return nil, "invalid_sampling_interval"
    end
    local resulting, changed = events, {}
    if current.pon_state ~= previous.pon_state then
        resulting = push_bounded(resulting, {
            kind = "pon_state_change",
            from = previous.pon_state,
            to = current.pon_state,
            at_uptime = current.uptime,
            observation_window_seconds = elapsed,
            walltime_trust = "unknown",
        }, limit)
        changed[#changed + 1] = "pon"
    end
    if current.ethernet_mbps ~= previous.ethernet_mbps then
        resulting = push_bounded(resulting, {
            kind = "host_link_change",
            from = previous.ethernet_mbps,
            to = current.ethernet_mbps,
            at_uptime = current.uptime,
            observation_window_seconds = elapsed,
            walltime_trust = "unknown",
        }, limit)
        changed[#changed + 1] = "ethernet"
    end
    return resulting, (#changed > 0 and table.concat(changed, ",") or "unchanged")
end

return M
