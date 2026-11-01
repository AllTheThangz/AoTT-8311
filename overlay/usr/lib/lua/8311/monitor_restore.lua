-- r8 boot restore: use the already-installed vendor UCI CLI before rpcd/logd.
-- Executed at startup, never from the PON, monitoring or flash write paths.
local store = require "8311.monitor_store"
local web = require "8311.webutil"
local M = {}
local keys = {
    "log_remote", "log_ip", "log_port", "log_proto",
    "aott_metrics", "aott_metrics_client", "aott_metrics_sha256"
}

local function actual_cli(argv)
    local code, output, overflow = web.capture(argv, 1024)
    if code ~= 0 or overflow then return nil end
    return (output or ""):gsub("[\r\n]+$", "")
end

function M.run(command, source)
    command = command or actual_cli
    source = source or store
    local record = source.read()
    if not record then
        -- First boot without a record, missing ptconf or invalid permissions:
        -- no UCI changes and no attempt to enable any collector.
        return nil, "Persistent monitoring configuration unavailable"
    end
    if not source.valid(record) then
        return nil, "Persistent monitoring record is invalid"
    end
    local cli = {"/usr/bin/timeout", "-k", "1", "3", "/sbin/uci", "-q"}
    local function invoke(action, value)
        local argv = {}
        for i,v in ipairs(cli) do argv[i]=v end
        argv[#argv+1]=action
        if value ~= nil then argv[#argv+1]=value end
        return command(argv)
    end
    if invoke("get", "system.@system[0]") ~= "system" then
        return nil, "System settings not initialized"
    end
    local changed = false
    for _, key in ipairs(keys) do
        local uci_name = "system.@system[0]." .. key
        local existing = invoke("get", uci_name)
        if existing ~= record[key] then
            -- Every value was fully validated by the durable store parser.
            if invoke("set", uci_name .. "=" .. record[key]) == nil then
                return nil, "Unable to restore monitoring option"
            end
            changed = true
        end
    end
    if changed then
        if invoke("commit", "system") == nil then
            return nil, "Unable to commit monitoring restoration"
        end
    end
    for _, key in ipairs(keys) do
        if invoke("get", "system.@system[0]." .. key) ~= record[key] then
            return nil, "Monitoring restoration verification failed"
        end
    end
    return true, changed and "restored" or "already-current"
end

return M
