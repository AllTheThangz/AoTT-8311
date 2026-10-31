-- Offline compatibility tests for the read-only PON Managed Entity Explorer.
-- All OMCI values below are synthetic, including malicious HTML.
-- No device, HTTP server, PON identity, or configuration writer is contacted.

local capture_mode = "listing"
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
    return {html_escape=escape}
end
package.preload["luci.util"] = function() return {} end
package.preload["luci.template"] = function()
    return {render=function(name, values) captured.name=name;captured.values=values end}
end
package.preload["luci.http"] = function()
    return {
        formvalue=function() return nil end,
        header=function(name, value) headers[name]=value end,
        status=function(code) last_status=code end,
        prepare_content=function(content_type) captured.content_type=content_type end,
        write=function(text) messages[#messages+1]=text end,
    }
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
package.preload["8311.config"] = function() return {} end
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
assert(headers["Cache-Control"] == "no-store", "Raw OMCI response must not be cached")
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
assert(headers["Cache-Control"] == "no-store", "Failure response must not be cached")

print("PON ME Explorer: 7 offline privacy and routing checks passed")
