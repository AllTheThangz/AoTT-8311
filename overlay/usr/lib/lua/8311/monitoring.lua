-- AoTT-8311 v2r8 candidate: bounded logging and optional authenticated metrics.
-- Reuses OpenWrt UCI and logread/logd; no additional background service.
-- All writes affect the system logging section only.
local uci_lib = require "luci.model.uci"
local web = require "8311.webutil"
local sys = require "luci.sys"
local M = {}

local options = {"log_remote", "log_ip", "log_port", "log_proto", "aott_metrics"}
local allowed = {
    token=true, revision=true, log_remote=true, log_ip=true,
    log_port=true, log_proto=true, aott_metrics=true
}

local function system_section(u)
    local id
    u:foreach("system", "system", function(s)
        id = s[".name"]
        return false
    end)
    return id
end

local function original_options(u, section)
    local out = {}
    for _, key in ipairs(options) do
        local value = u:get("system", section, key)
        if value ~= nil and type(value) ~= "string" then
            return nil, "Logging settings are not readable"
        end
        out[key] = value
    end
    return out
end

local function revision_of(raw)
    local parts = {}
    for _, key in ipairs(options) do
        parts[#parts + 1] = key .. "=" .. (raw[key] or "<unset>")
    end
    return web.digest_text(table.concat(parts, "\n"))
end

function M.snapshot(u)
    u = u or uci_lib.cursor()
    local section = system_section(u)
    if not section then return nil, "System logging configuration is unavailable" end
    local raw, err = original_options(u, section)
    if not raw then return nil, err end
    local revision, why = revision_of(raw)
    if not revision then return nil, why end
    local ip = raw.log_ip or ""
    local effective = raw.log_remote == "1" or
        (raw.log_remote == nil and ip ~= "") -- log service defaults remote to on.
    local enabled = effective and ip ~= ""
    return {
        section=section, original=raw, revision=revision,
        log_remote=enabled and "1" or "0",
        log_ip=ip,
        log_port=raw.log_port or "514",
        log_proto=raw.log_proto or "udp",
        aott_metrics=raw.aott_metrics == "1" and "1" or "0",
        transport_udp=true, transport_tcp=true,
        severity_filter_available=false,
        configured=enabled
    }
end

local function valid_destination(v)
    if type(v) ~= "string" or #v > 253 or v == "" then return false end
    if v:find("[%z\1-\32\127]") or v:find("[^%w%.%-]") then return false end
    if v:sub(1,1) == "." or v:sub(-1) == "." or v:find("..", 1, true) then
        return false
    end
    local parts, count = {}, 0
    for part in v:gmatch("[^.]+") do
        count = count + 1
        if #part > 63 or part:sub(1,1) == "-" or part:sub(-1) == "-" then
            return false
        end
        parts[count] = part
    end
    if count == 0 then return false end
    if v:match("^[%d%.]+$") then
        if count ~= 4 then return false end
        for _, part in ipairs(parts) do
            local number = tonumber(part)
            if not number or number > 255 or #part > 3 then return false end
        end
        local all_zero, all_255 = true, true
        for _, part in ipairs(parts) do
            all_zero = all_zero and tonumber(part) == 0
            all_255 = all_255 and tonumber(part) == 255
        end
        if all_zero or all_255 then return false end
    end
    return true
end

function M.validate(values)
    if type(values) ~= "table" then return nil, "Invalid logging request" end
    for key, val in pairs(values) do
        if not allowed[key] or type(val) ~= "string" then
            return nil, "Unknown or duplicate monitoring field"
        end
    end
    if type(values.revision) ~= "string" or
       not values.revision:match("^[0-9a-f]+$") or #values.revision ~= 64 then
        return nil, "Refresh monitoring settings before saving"
    end
    local a = values.log_remote
    local b = values.aott_metrics
    if (a ~= "0" and a ~= "1") or (b ~= "0" and b ~= "1") then
        return nil, "Use Enabled or Disabled for monitoring switches"
    end
    local ip = values.log_ip
    if type(ip) ~= "string" or #ip > 253 or ip:find("[%z\1-\32\127]") then
        return nil, "Invalid log receiver address"
    end
    if ip ~= "" and not valid_destination(ip) then
        return nil, "Use a valid IPv4 address or DNS hostname"
    end
    if a == "1" and ip == "" then
        return nil, "A receiver address is required before enabling syslog"
    end
    local port = values.log_port
    if type(port) ~= "string" or not port:match("^%d+$") or #port > 5
       or tonumber(port) < 1 or tonumber(port) > 65535 then
        return nil, "Port must be between 1 and 65535"
    end
    if values.log_proto ~= "udp" and values.log_proto ~= "tcp" then
        return nil, "Unsupported syslog transport"
    end
    return {
        log_remote=a, log_ip=ip, log_port=tostring(tonumber(port)),
        log_proto=values.log_proto, aott_metrics=b
    }
end

local function set_options(u, section, values)
    for _, key in ipairs(options) do
        local value = values[key]
        local ok
        if value == nil then
            ok = u:get("system", section, key) == nil or
                u:delete("system", section, key)
        else
            ok = u:set("system", section, key, value)
        end
        if not ok then return nil, "Logging configuration write failed" end
    end
    return true
end

local function reload_logger()
    local code, _, overflow = web.capture({
        "/usr/bin/timeout", "-k", "1", "5", "/etc/init.d/log", "reload"
    }, 2048)
    return code == 0 and not overflow
end

-- The lock covers the fresh read, single-package UCI commit and reload.
-- A failed reload triggers best-effort rollback and explicit failure.
function M.apply(form)
    local values, why = M.validate(form)
    if not values then return nil, why, 422 end
    local fd = web.lock("/tmp/8311-monitoring.lock")
    if not fd then return nil, "Monitoring settings are busy; retry", 409 end
    local function finish(result, error, status)
        fd:close()
        return result, error, status
    end
    local u = uci_lib.cursor()
    local changes = u:changes("system")
    if type(changes) ~= "table" or next(changes) then
        return finish(nil, "Other system configuration changes are pending; apply them first", 409)
    end
    local before, err = M.snapshot(u)
    if not before then return finish(nil, err, 503) end
    if form.revision ~= before.revision then
        return finish(nil, "Settings changed; refresh and review before saving", 409)
    end
    local ok, seterr = set_options(u, before.section, values)
    if not ok then
        u:revert("system")
        return finish(nil, seterr, 503)
    end
    local committed = u:commit("system")
    if committed and reload_logger() then
        local after = M.snapshot(uci_lib.cursor())
        if after and after.log_remote == values.log_remote
            and after.log_ip == values.log_ip
            and after.log_port == values.log_port
            and after.log_proto == values.log_proto
            and after.aott_metrics == values.aott_metrics then
            return finish(after, nil, 200)
        end
    end

    -- Persist the original exact values, including previously absent options.
    local rescue = uci_lib.cursor()
    local restored = set_options(rescue, before.section, before.original)
    local saved = restored and rescue:commit("system")
    local restarted = saved and reload_logger()
    local verified
    if restarted then
        local state = M.snapshot(uci_lib.cursor())
        verified = state and state.revision == before.revision
    end
    if verified then
        return finish(nil, "Monitoring apply failed; previous settings restored", 503)
    end
    return finish(nil, "Monitoring apply failed and rollback could not be verified; inspect system logging", 503)
end

function M.send_test()
    local state, err = M.snapshot()
    if not state then return nil, err end
    if state.log_remote ~= "1" then
        return nil, "Enable and save remote logging before sending a test"
    end
    local marker = sys.uniqueid(8)
    if type(marker) ~= "string" or not marker:match("^[0-9a-f]+$") or #marker ~= 16 then
        return nil, "Unable to generate a test event ID"
    end
    local code, _, overflow = web.capture({
        "/usr/bin/timeout", "-k", "1", "3",
        "/usr/bin/logger", "-t", "aott-8311", "Remote syslog test " .. marker
    }, 512)
    if code ~= 0 or overflow then return nil, "Local test event was not accepted" end
    return {event_id=marker, receiver_confirmed=false,
        note="Local test event generated. Confirm receipt using your own syslog collector."}
end

function M.metrics_enabled()
    -- Avoid a revision hash, temporary file and external subprocess
    -- on every external metrics scrape.
    local u = uci_lib.cursor()
    local section = system_section(u)
    return section and u:get("system", section, "aott_metrics") == "1" or false
end

return M
