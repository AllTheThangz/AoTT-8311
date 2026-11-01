-- Isolated v2r8 syslog and metrics tests. No device, sockets, or UCI writes.
local module_path = assert(arg[1], "Provide the Lua monitoring module path")
local stored = {log_remote="0", log_port="514", log_proto="udp"}
local pending = {}
local DELETED = {}
local reload_calls = 0
local log_calls = 0
local fail_reload_once = false
local lock_held = false

local function cursor()
    local u = {}
    function u:foreach(config, section_type, fn)
        assert(config == "system" and section_type == "system")
        return fn({[".name"]="test-system"})
    end
    function u:get(config, section, key)
        assert(config == "system" and section == "test-system")
        if pending[key] ~= nil then
            if pending[key] == DELETED then return false end
            return pending[key]
        end
        if stored[key] == nil then return false end
        return stored[key]
    end
    function u:get_all(config, section)
        if config == "network" then
            if section == "lct" then return {ipaddr=("192" .. ".0.2.1")} end
            return nil
        end
        assert(config == "system" and section == "test-system")
        local result = {[".type"]="system", [".name"]=section}
        for key, value in pairs(stored) do result[key]=value end
        for key, value in pairs(pending) do
            if value == DELETED then result[key] = nil else result[key] = value end
        end
        return result
    end
    function u:set(config, section, key, value)
        assert(config == "system" and section == "test-system")
        pending[key] = value
        return true
    end
    function u:delete(config, section, key)
        pending[key] = DELETED
        return true
    end
    function u:changes(config)
        assert(config == "system")
        local out = {}
        for k,v in pairs(pending) do out[k]=v end
        return out
    end
    function u:revert(config)
        assert(config == "system")
        pending = {}
        return true
    end
    function u:commit(config)
        assert(config == "system")
        for k, v in pairs(pending) do
            if v == DELETED then stored[k] = nil else stored[k] = v end
        end
        pending = {}
        return true
    end
    return u
end

package.preload["luci.model.uci"] = function()
    return {cursor=cursor}
end
package.preload["8311.webutil"] = function()
    return {
        digest_text=function(t)
            local h=1
            for i=1,#t do h = (h*33 + t:byte(i)) % 104729 end
            return string.format("%064x", h)
        end,
        lock=function(path)
            assert(path == "/tmp/8311-monitoring.lock")
            assert(not lock_held, "monitoring lock already held")
            lock_held = true
            return {close=function()
                assert(lock_held)
                lock_held = false
            end}
        end,
        capture=function(argv, limit)
            assert(limit <= 2048)
            if argv[5] == "/etc/init.d/log" then
                assert(argv[6] == "reload")
                reload_calls = reload_calls + 1
                if fail_reload_once then
                    fail_reload_once = false
                    return 1, "", false
                end
                return 0, "", false
            end
            if argv[5] == "/usr/bin/logger" then
                assert(argv[6] == "-t" and argv[7] == "aott-8311")
                assert(argv[8]:find("Remote syslog test "))
                log_calls = log_calls + 1
                return 0, "", false
            end
            error("Unexpected command")
        end,
    }
end
package.preload["luci.sys"] = function()
    return {uniqueid=function(n)
        if n == 8 then return "0123456789abcdef" end
        assert(n == 32)
        return string.rep("a",64)
    end}
end

local monitor = assert(loadfile(module_path))()
assert(cursor():get("system", "test-system", "log_ip") == false)
local old = assert(monitor.snapshot())
assert(old.log_remote == "0")
assert(old.aott_metrics == "0")
assert(old.log_port == "514")
assert(not monitor.metrics_enabled())
local form = {
    revision=old.revision, token="irrelevant-in-isolated-stub",
    log_remote="1", log_ip="collector.example.com", log_port="5514",
    log_proto="tcp", aott_metrics="0", aott_metrics_client=""
}
local validated = assert(monitor.validate(form))
assert(validated.log_ip == "collector.example.com")
local bads = {
    {field="log_ip", value="bad;touch /tmp/x"},
    {field="log_ip", value="256" .. ".1.1.1"},
    {field="log_ip", value="example..net"},
    {field="log_ip", value="-bad.example.com"},
    {field="log_ip", value="no spaces.example"},
    {field="log_port", value="0"},
    {field="log_port", value="65536"},
    {field="log_port", value="514a"},
    {field="log_proto", value="tls"},
    {field="aott_metrics", value="on"},
    {field="log_remote", value="true"},
}
for _, bad in ipairs(bads) do
    local copy={}
    for k,v in pairs(form) do copy[k]=v end
    copy[bad.field] = bad.value
    local values, err = monitor.validate(copy)
    assert(not values and err, "Rejected " .. bad.field)
end
do
    local copy={}
    for k,v in pairs(form) do copy[k]=v end
    copy.unrecognized="1"
    assert(monitor.validate(copy) == nil)
end
local done, err, code = monitor.apply(form)
assert(done and not err and code == 200)
assert(done.log_remote == "1" and done.aott_metrics == "0")
assert(done.log_proto == "tcp" and done.log_port == "5514")
assert(reload_calls == 1 and not lock_held)
assert(not monitor.metrics_enabled())
local latest = assert(monitor.snapshot())
assert(latest.revision ~= old.revision)
local stale, serr, status = monitor.apply(form)
assert(stale == nil and status == 409)
assert(stored.log_port == "5514" and not lock_held)
local result, why = monitor.send_test()
assert(result and result.event_id == "0123456789abcdef" and result.receiver_confirmed == false)
assert(not why and log_calls == 1)
assert(stored.log_ip == "collector.example.com")
local rollback_form = {
    revision=latest.revision,
    log_remote="1", log_ip="collector.example.com", log_port="5515",
    log_proto="udp", aott_metrics="0", aott_metrics_client=""
}
fail_reload_once=true
local failed, warning, failure_code = monitor.apply(rollback_form)
assert(not failed and failure_code == 503)
assert(warning:find("restored"))
assert(stored.log_port == "5514" and stored.log_proto == "tcp")
assert(monitor.snapshot().revision == latest.revision)
assert(not lock_held)
assert(reload_calls == 3) -- successful apply, failed apply, successful rollback
-- Read-only external collector credentials are independent from admin login.
local before_token = assert(monitor.snapshot())
assert(before_token.aott_metrics == "0" and not before_token.credential_configured)
local generated, problem, http_status =
    monitor.change_credential(before_token.revision, "rotate")
assert(generated and not problem and http_status == 200)
assert(generated.credential_configured and #generated.collector_token == 64)
assert(stored.aott_metrics_sha256 and #stored.aott_metrics_sha256 == 64)
assert(stored.aott_metrics_sha256 ~= generated.collector_token)
assert(monitor.snapshot().revision ~= before_token.revision)
assert(not lock_held)

local obsolete, why_stale, stale_status =
    monitor.change_credential(before_token.revision, "revoke")
assert(not obsolete and stale_status == 409 and why_stale)
local credential_state = assert(monitor.snapshot())
local allowed_client = ("192" .. ".0.2.40")
local guarded_form = {
    revision=credential_state.revision,
    log_remote="1", log_ip="collector.example.com", log_port="5514",
    log_proto="tcp", aott_metrics="1",
    aott_metrics_client=allowed_client
}
local enabled, why_enable, enable_status = monitor.apply(guarded_form)
assert(enabled and enable_status == 200 and not why_enable)
assert(enabled.credential_configured and enabled.aott_metrics == "1")
assert(enabled.aott_metrics_client == allowed_client)
assert(reload_calls == 3) -- a credential-only change must not restart logd
assert(monitor.metrics_enabled())

local env = {
    HTTPS="on", REMOTE_ADDR=allowed_client, SERVER_ADDR=("192" .. ".0.2.1"),
    HTTP_X_AOTT_METRICS_TOKEN=generated.collector_token
}
local function getenv(name) return env[name] end
assert(monitor.collector_authorized(getenv))
assert(not monitor.collector_authorized(nil))
env.HTTPS="off"; assert(not monitor.collector_authorized(getenv)); env.HTTPS="on"
env.REMOTE_ADDR=("192" .. ".0.2.41")
env.HTTP_X_FORWARDED_FOR=allowed_client
assert(not monitor.collector_authorized(getenv))
env.REMOTE_ADDR=allowed_client
env.SERVER_ADDR=("192" .. ".0.2.2"); assert(not monitor.collector_authorized(getenv))
env.SERVER_ADDR=("192" .. ".0.2.1")
env.HTTP_X_AOTT_METRICS_TOKEN=string.rep("b",64)
assert(not monitor.collector_authorized(getenv))
env.HTTP_X_AOTT_METRICS_TOKEN=generated.collector_token
assert(monitor.collector_authorized(getenv))
local rejects = {
    {aott_metrics_client=""},
    {aott_metrics_client=("0" .. ".0.0.0")},
    {aott_metrics_client=("224" .. ".1.1.1")},
    {aott_metrics_client=("192" .. ".0.2.40/32")},
    {aott_metrics_client=("192" .. ".0.2.040")}
}
for _, mutation in ipairs(rejects) do
    local invalid = {}
    for k,v in pairs(guarded_form) do invalid[k]=v end
    invalid.revision=monitor.snapshot().revision
    for k,v in pairs(mutation) do invalid[k]=v end
    local prepared = monitor.validate(invalid)
    assert(prepared == nil, "Invalid collector address accepted")
end
local denied = {}
for k,v in pairs(guarded_form) do denied[k]=v end
denied.revision=monitor.snapshot().revision
denied.aott_metrics_sha256=generated.collector_token
assert(monitor.validate(denied)==nil)

local current = assert(monitor.snapshot())
local revoked, rev_err, rev_status =
    monitor.change_credential(current.revision, "revoke")
assert(revoked and rev_status == 200 and not rev_err)
assert(revoked.credential_configured == false and not revoked.collector_token)
assert(stored.aott_metrics_sha256 == nil)
assert(not monitor.metrics_enabled())
assert(not monitor.collector_authorized(getenv))
assert(not lock_held)
print("MONITORING_FIXTURE_PASS")
