-- Offline compatibility tests for the read-only PON Managed Entity Explorer.
-- All OMCI values below are synthetic, including malicious HTML.
-- No device, HTTP server, PON identity, or configuration writer is contacted.

local capture_mode = "listing"
local collector_allowed = false
local collector_enabled = true
local collector_method = "GET"
local collector_metrics_calls = 0
local collector_metrics_fail = false
local captured = {}
local headers, messages, last_response, last_status = {}, {}, nil, nil

local sample = table.concat({
    "Found 2 managed entities in the MIB:",
    "| Class id | Instance id | Class name",
    "| 278 | 1 (Example <script>alert(1)</script> & entity)",
    "| 99999 | 1 (Invalid oversized identifier <img src=x onerror=x>)",
}, "\n")

local function escape(value)
    return tostring(value):gsub("&", "&amp;"):gsub("<", "&lt;")
        :gsub(">", "&gt;"):gsub('"', "&quot;"):gsub("'", "&#39;")
end

package.preload["8311.tools"] = function()
    return {
        html_escape=escape,
        metrics=function(bounded)
            collector_metrics_calls = collector_metrics_calls + 1
            assert(bounded == true)
            if collector_metrics_fail then
                error("SYNTHETIC_INTERNAL_SENSOR_ERROR_MUST_NOT_LEAK")
            end
            return {rx_power_dBm=-13.8, ploam_state=51}
        end,
        metric_names=function()
            return {"rx_power_dBm", "ploam_state"}
        end,
        is_finite=function(v)
            return type(v) == "number" and v == v and math.abs(v) < math.huge
        end
    }
end
package.preload["luci.util"] = function() return {} end
package.preload["luci.template"] = function()
    return {render=function(name, values) captured.name=name;captured.values=values end}
end
package.preload["luci.http"] = function()
    luci = luci or {}
    local implementation = {
        formvalue=function() return nil end,
        getenv=function(name)
            return name == "REQUEST_METHOD" and collector_method or nil
        end,
        header=function(name, value) headers[name]=value end,
        status=function(code) last_status=code end,
        prepare_content=function(content_type) captured.content_type=content_type end,
        write=function(text) messages[#messages+1]=text end,
    }
    luci.http = implementation
    return implementation
end
package.preload["luci.dispatcher"] = function()
    return {
        build_url=function(...)
            return "/cgi-bin/luci/" .. table.concat({...}, "/")
        end,
    }
end
package.preload["luci.sys"] = function() return {} end
package.preload["luci.i18n"] = function() return {translate=function(x) return x end} end
package.preload["base64"] = function() return {} end
package.preload["luci.ltn12"] = function() return {} end
package.preload["nixio.fs"] = function() return {} end
package.preload["nixio.bit"] = function() return {} end
package.preload["luci.model.uci"] = function() return {} end
package.preload["luci.jsonc"] = function() return {} end
package.preload["8311.webutil"] = function()
    return {
        capture=function(args, limit)
            captured.command = args
            captured.limit = limit
            if capture_mode == "listing" then return 0,sample,false end
            if capture_mode == "success" then return 0,"Synthetic attribute: <text>",false end
            return 1,"SENSITIVE_RUNTIME_VALUE_SHOULD_NOT_LEAK",false
        end,
        reply=function(_,code,body)
            last_response={status=code, body=body}
            return last_response
        end,
    }
end
package.preload["8311.health"] = function() return {} end
package.preload["8311.monitoring"] = function()
    return {
        collector_authorized=function() return collector_allowed end,
        metrics_enabled=function() return collector_enabled end
    }
end
package.preload["8311.effective_probe"] = function()
    return {live_management=function() return nil,"synthetic_readonly_unavailable" end}
end
package.preload["8311.effective_device_probe"] = function()
    return {live_device=function() return nil,"synthetic_readonly_unavailable" end}
end
package.preload["8311.effective_pon_probe"] = function()
    return {live_pon=function() return nil,"synthetic_readonly_unavailable" end}
end
package.preload["8311.effective_vlan_probe"] = function()
    return {live_vlan=function() return nil,"synthetic_readonly_unavailable" end}
end
package.preload["8311.effective_hardware_probe"] = function()
    return {live_hardware=function() return nil,"synthetic_readonly_unavailable" end}
end
package.preload["8311.effective_reporting_probe"] = function()
    return {live_reporting=function() return nil,"synthetic_readonly_unavailable" end}
end
package.preload["8311.config"] = function() return {} end
package.preload["8311.history_config"] = function() return {} end
package.preload["8311.history_live_snapshot"] = function() return {} end
package.preload["8311.uploads"] = function() return {} end
package.preload["8311.jobs"] = function() return {} end

local path = assert(arg[1], "Controller source path is required")
local file = assert(loadfile(path))
file()
local controller = assert(package.loaded["luci.controller.8311"])
assert(type(controller.action_pon_explorer) == "function", "Missing Explorer action")
assert(type(controller.action_pon_dump) == "function", "Missing read-only ME detail action")

controller.action_pon_explorer()
assert(captured.name == "8311/pon_me", "Unexpected Explorer template")
assert(headers["Cache-Control"] == "no-store, private",
       "OMCI listing page must not be cached")
assert(headers["X-Content-Type-Options"] == "nosniff",
       "OMCI listing page must disable content sniffing")
local rendered = assert(captured.values.omci)
assert(rendered:find('href="/cgi%-bin/luci/admin/8311/pon_dump/278/1"'),
       "Explorer must generate absolute, dispatcher-owned ME links")
assert(rendered:find('data%-me%-id="278"'), "Valid entry must be selectable")
assert(not rendered:find('data%-me%-id="99999"'), "Oversized class id must not be selectable")
assert(rendered:find("&lt;script&gt;", 1, true), "Untrusted markup not escaped")
assert(not rendered:find("<script>", 1, true), "Untrusted script rendered")

capture_mode = "success"
messages = {}
controller.action_pon_dump("278", "1")
assert(headers["Cache-Control"] == "no-store, private", "Raw OMCI response must not be cached")
assert(headers["X-Content-Type-Options"] == "nosniff",
       "OMCI detail response must disable content sniffing")
assert(captured.content_type == "text/plain; charset=utf-8", "ME response must be plain text")
assert(captured.command[1] == "/usr/bin/omci_pipe.sh"
    and captured.command[2] == "meg"
    and captured.command[3] == "278" and captured.command[4] == "1",
    "Read-only OMCI command must receive checked decimal ids")
assert(messages[1] == "Synthetic attribute: <text>", "ME attributes not returned as plain text")

local count = #messages
controller.action_pon_dump("not-a-number", "1")
assert(last_response and last_response.status == 400, "Non-decimal IDs must fail closed")
assert(#messages == count, "Malformed ID must not generate output")

controller.action_pon_dump("65536", "1")
assert(last_response.status == 400, "Out-of-range IDs must fail closed")

capture_mode = "failure"
messages = {}
controller.action_pon_dump("278", "1")
assert(last_status == 502, "Unavailable OMCI lookup must return an error status")
assert(messages[1] == "Managed entity lookup did not complete successfully.",
    "Lookup error leaked a raw OMCI response")
assert(headers["Cache-Control"] == "no-store, private", "Failure response must not be cached")

-- The public-path collector route may exist, but without bearer credentials
-- its action must deny requests before any optical metrics are read.
last_response = nil
controller.action_collector_metrics()
assert(last_response and last_response.status == 403,
       "Collector endpoint must deny unauthenticated requests")
assert(headers["Cache-Control"] == "no-store, private")
assert(headers["X-Content-Type-Options"] == "nosniff")
-- Invalid HTTP method must fail before executing metrics.
collector_method = "POST"
local checked = collector_metrics_calls
last_response = nil
controller.action_collector_metrics()
assert(last_response and last_response.status == 405)
assert(collector_metrics_calls == checked)
collector_method = "GET"

-- A successfully authorized request may expose only bounded numeric data.
collector_allowed = true
messages = {}
last_response = nil
controller.action_collector_metrics()
assert(last_response == nil)
assert(collector_metrics_calls == checked + 1)
assert(captured.content_type == "application/json")
local response_json = table.concat(messages)
assert(response_json:find('"rx_power_dBm": %-13%.80'))
assert(response_json:find('"ploam_state": 51'))
assert(not response_json:find("secret", 1, true))
assert(not response_json:find("SYNTHETIC_INTERNAL_SENSOR_ERROR", 1, true))
assert(headers["Referrer-Policy"] == "no-referrer")
assert(headers["Cache-Control"] == "no-store, private")

-- An administrator-disabled exporter must fail closed even with a valid
-- token: no optical read, no exception details.
collector_enabled = false
messages = {}
last_response = nil
controller.action_collector_metrics()
assert(last_response and last_response.status == 403)
assert(collector_metrics_calls == checked + 1)
collector_enabled = true

-- An internal sensor failure is 503, never a leaked raw device error.
collector_metrics_fail = true
last_response = nil
controller.action_collector_metrics()
assert(last_response and last_response.status == 503)
assert(not tostring(last_response.body.error):find("SYNTHETIC_INTERNAL_SENSOR",1,true))

print("PON ME Explorer: 7 offline privacy and routing checks passed; collector authorized and denied cases passed")
