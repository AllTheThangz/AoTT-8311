-- H-011/H-021 PRX126 observation adapter.
-- Used only by the opt-in, foreground RAM-only history worker. No new
-- native sampler process, flash-history write or subscriber WAN probe.
-- The fixed native wrapper uses only read-only commands and bounded output.
local history = require "8311.history_sampler"
local pon_model = require "8311.effective_pon_state"
local counter_model = require "8311.history_model"
local M = {}

local BOOT_PATH = "/proc/sys/kernel/random/boot_id"
local UPTIME_PATH = "/proc/uptime"
local SPEED_PATH = "/sys/class/net/eth0_0/speed"
local PON_CMD = {"/usr/bin/timeout","-k","1","3","/usr/bin/pon","psg"}
local ETH_CMD = {"/usr/bin/timeout","-k","1","4",
                 "/usr/sbin/ethtool","-S","eth0_0"}
local BOOT_BYTES, UPTIME_BYTES, SPEED_BYTES = 80, 80, 32
local PON_BYTES, ETH_BYTES = 1024, 16384

local function clean_boot(raw)
    if type(raw) ~= "string" or #raw > BOOT_BYTES then return nil end
    raw = raw:gsub("[\r\n]+$", ""):lower()
    if #raw ~= 36 or not raw:match(
        "^%x%x%x%x%x%x%x%x%-%x%x%x%x%-%x%x%x%x%-%x%x%x%x%-%x%x%x%x%x%x%x%x%x%x%x%x$") then
        return nil
    end
    if raw:gsub("[%-0]", "") == "" then return nil end
    return raw
end

local function clean_uptime(raw)
    if type(raw) ~= "string" or #raw > UPTIME_BYTES then return nil end
    local uptime = raw:match("^%s*(%d+%.?%d*)%s+%d+%.?%d*%s*$")
    if not uptime then return nil end
    local n = tonumber(uptime)
    if not n or n ~= n or n < 0 or n > 1e12 or n == math.huge then
        return nil
    end
    return n
end

local function clean_speed(raw)
    if type(raw) ~= "string" or #raw > SPEED_BYTES then return nil end
    local digits = raw:match("^%s*(%d+)%s*$")
    if not digits or #digits > 6 then return nil end
    local speed = tonumber(digits)
    if not speed or speed < 0 or speed > 100000 then return nil end
    return speed
end

-- Do not turn ethtool counters into doubles. Parse exact decimal strings.
-- Unknown counters and all command banners, serials and messages are dropped.
local function parse_ethtool(raw)
    if type(raw) ~= "string" or #raw > ETH_BYTES or
       raw:find("[%z\1-\8\11\12\14-\31\127]") then
        return nil, "invalid_eth_report"
    end
    local counters, seen = {}, {}
    for line in (raw .. "\n"):gmatch("(.-)\n") do
        local key, value = line:match("^%s*([%w_]+):%s*(%d+)%s*$")
        if key == "RxGoodBytes" or key == "TxGoodBytes" or
           key == "RxFCSErrorPkts" or key == "RxOverflowError" or
           key == "RxDroppedPkts" or key == "TxDroppedPkts" then
            if seen[key] then return nil, "ambiguous_eth_counter" end
            seen[key] = true
            -- A counter outside unsigned-64 range is never rounded or
            -- silently coerced to a lower integer.
            if #value > 20 or counter_model.counter_delta("0",value) == nil then
                return nil, "invalid_eth_counter"
            end
            counters[key] = value
        end
    end
    if not next(counters) then return nil, "no_eth_counters" end
    return counters
end

local function read(provider, path, maximum)
    local ok, value = pcall(provider.read, path, maximum)
    if not ok or type(value) ~= "string" or #value > maximum then return nil end
    return value
end

local function capture(provider, argv, maximum)
    local ok, code, output, overflow = pcall(provider.run, argv, maximum)
    if not ok or code ~= 0 or overflow ~= false or
       type(output) ~= "string" or #output > maximum then
        return nil
    end
    return output
end

-- Provider callbacks are injected for offline host and vendor-MIPS testing.
-- Only fixed kernel paths and fixed read-only argv are ever requested.
function M.read_selected(provider, selected)
    if type(selected)~="table" or type(selected.pon)~="boolean" or
       type(selected.host)~="boolean" or
       (not selected.pon and not selected.host) then
        return nil,"invalid_probe_selection"
    end
    for key in pairs(selected) do
        if key~="pon" and key~="host" then
            return nil,"invalid_probe_selection"
        end
    end
    if type(provider) ~= "table" or type(provider.read) ~= "function" or
       type(provider.run) ~= "function" then
        return nil, "invalid_readonly_provider"
    end
    local boot = clean_boot(read(provider, BOOT_PATH, BOOT_BYTES))
    if not boot then return nil, "boot_identity_unavailable" end
    local uptime_start = clean_uptime(read(provider, UPTIME_PATH, UPTIME_BYTES))
    if not uptime_start then return nil, "monotonic_time_unavailable" end

    local speed = selected.host and
        clean_speed(read(provider, SPEED_PATH, SPEED_BYTES)) or nil
    local pon_output = selected.pon and
        capture(provider, PON_CMD, PON_BYTES) or nil
    local pon = nil
    if pon_output then pon = pon_model.parse_pon_status(pon_output) end
    local eth_output = selected.host and
        capture(provider, ETH_CMD, ETH_BYTES) or nil
    local counters = nil
    if eth_output then counters = parse_ethtool(eth_output) end

    -- Enclose every native observation in a bounded monotonic window.
    -- A reboot midway through collection must not mix boot epochs, and a
    -- stalled or interrupted read must not be mistaken for fresh telemetry.
    local uptime_end = clean_uptime(read(provider, UPTIME_PATH, UPTIME_BYTES))
    if not uptime_end then return nil, "observation_window_unavailable" end
    if uptime_end < uptime_start or uptime_end - uptime_start > 12 then
        return nil, "observation_window_out_of_bounds"
    end
    local boot_end = clean_boot(read(provider, BOOT_PATH, BOOT_BYTES))
    if not boot_end or boot_end ~= boot then
        return nil, "boot_changed_during_observation"
    end

    -- A missing or failed individual probe is reported as unavailable,
    -- never as zero loss, a downed fiber, or a working Internet connection.
    local availability = {
        pon = not selected.pon and "not_sampled" or
            (pon ~= nil and "observed" or "unavailable"),
        host_link = not selected.host and "not_sampled" or
            (speed ~= nil and "observed" or "unavailable"),
        host_counters = not selected.host and "not_sampled" or
            (counters ~= nil and "observed" or "unavailable"),
        proves_subscriber_internet = false,
        sample_source = "prx126_native_host_interface_eth0_0",
        no_device_write = true,
        observation_window_seconds = uptime_end - uptime_start,
    }
    return {
        boot = boot, uptime = uptime_end, source = "eth0_0",
        pon_state = pon, ethernet_mbps = speed,
        eth = counters or {},
        observed={pon=selected.pon,host=selected.host},
    }, availability
end

-- Legacy one-shot reader remains a two-channel observation.
function M.read_once(provider)
    return M.read_selected(provider,{pon=true,host=true})
end

-- One explicit invocation, no timers or background services. The result is
-- a redacted receipt, not the boot ID or full provider readings.
function M.collect_one(state, provider)
    -- Reject invalid collector state *before* starting either native command.
    if type(state) ~= "table" or state.schema ~= 1 or
       type(state.samples) ~= "table" or type(state.events) ~= "table" then
        return nil, "invalid_state"
    end
    local snapshot, availability_or_error = M.read_once(provider)
    if not snapshot then return nil, availability_or_error end
    local receipt, why = history.ingest(state, snapshot)
    if not receipt then return nil, why end
    return {
        status = receipt.status,
        samples_retained = receipt.samples_retained,
        events_retained = receipt.events_retained,
        events_added = receipt.events_added,
        has_rate = receipt.has_rate,
        availability = availability_or_error,
        source_only_not_hardware_qualified = true,
        no_device_write = true,
    }
end

-- Does not register a service, scheduler or HTTP endpoint. The explicit
-- caller must use this only after per-board qualification and load testing.
function M.native_once(state)
    local fs = require "nixio.fs"
    local web = require "8311.webutil"
    return M.collect_one(state, {
        read = function(path, maximum)
            return fs.readfile(path, maximum)
        end,
        run = function(argv, maximum)
            return web.capture(argv, maximum)
        end,
    })
end

M.parsers = {boot=clean_boot, uptime=clean_uptime, speed=clean_speed,
             ethtool=parse_ethtool}
return M
