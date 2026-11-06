-- Offline boot restoration and failure-injection tests.
-- All UCI values, credentials and environment details are synthetic.
local path = assert(arg[1], "restore Lua module required")
local record = {
    schema=1, log_remote="1", log_ip="collector.example.com",
    log_port="5514", log_proto="udp", aott_metrics="1",
    aott_metrics_client="192" .. ".0.2.40",
    aott_metrics_sha256=string.rep("a",64),
}
local present, valid = true, true
local committed, pending, calls = {hostname="generic-test"}, {}, {}
local fail_set, fail_commit, fail_revert, unrelated_changes = nil,false,false,false

package.preload["8311.monitor_store"] = function()
    return {
        read=function() return present and record or nil end,
        valid=function(r) return valid and r == record end
    }
end
package.preload["8311.webutil"] = function()
    return {capture=function() error("Unexpected raw capture") end}
end
local restore = assert(loadfile(path))()

local function mock_uci(argv)
    assert(argv[1] == "/usr/bin/timeout" and argv[2] == "-k")
    assert(argv[5] == "/sbin/uci" and argv[6] == "-q")
    local action, argument = argv[7], argv[8]
    calls[#calls+1] = action .. ":" .. (argument or "")
    if action == "changes" then
        assert(argument == "system")
        return unrelated_changes and "system.cfg0a.hostname='other'" or ""
    elseif action == "get" then
        if argument == "system.@system[0]" then return "system" end
        local field = assert(argument:match("^system%.@system%[0%]%.([a-z0-9_]+)$"))
        if pending[field] ~= nil then return pending[field] end
        return committed[field]
    elseif action == "set" then
        local field,value=argument:match("^system%.@system%[0%]%.([a-z0-9_]+)=(.*)$")
        assert(field and field ~= "hostname")
        if fail_set == field then return nil end
        pending[field] = value
        return ""
    elseif action == "commit" then
        assert(argument == "system")
        if fail_commit then return nil end
        for key,value in pairs(pending) do committed[key]=value end
        pending = {}
        return ""
    elseif action == "revert" then
        assert(argument == "system")
        if fail_revert then return nil end
        pending = {}
        return ""
    end
    error("Unexpected UCI operation " .. tostring(action))
end
local function count_ops(name)
    local n = 0
    for _,entry in ipairs(calls) do
        if entry:match("^" .. name .. ":") then n=n+1 end
    end
    return n
end
local function reset()
    committed={hostname="generic-test"}
    pending={}
    calls={}
    fail_set=nil; fail_commit=false; fail_revert=false
    unrelated_changes=false;present=true;valid=true
end

local success,stage=restore.run(mock_uci)
assert(success and stage == "restored")
assert(committed.hostname == "generic-test")
assert(count_ops("commit") == 1 and count_ops("revert")==0)
for key,value in pairs(record) do
    if key ~= "schema" then assert(committed[key]==value, "Not restored: "..key) end
end
calls={}
success,stage=restore.run(mock_uci)
assert(success and stage=="already-current")
assert(count_ops("set")==0 and count_ops("commit")==0)
assert(count_ops("changes")==1)

reset()
present=false
local denied, reason=restore.run(mock_uci)
assert(not denied and reason=="Persistent monitoring configuration unavailable")
assert(#calls==0)
reset()
valid=false
denied,reason=restore.run(mock_uci)
assert(not denied and reason=="Persistent monitoring record is invalid")
assert(#calls==0)

reset()
unrelated_changes=true
denied,reason=restore.run(mock_uci)
assert(not denied and reason=="Uncommitted system settings block monitoring restoration")
assert(count_ops("set")==0 and count_ops("revert")==0)

reset()
fail_set="log_port"
denied,reason=restore.run(mock_uci)
assert(not denied and reason:find("staged changes reverted"))
assert(count_ops("set")>=2 and count_ops("commit")==0 and count_ops("revert")==1)
assert(committed.hostname=="generic-test" and committed.log_remote==nil)
assert(next(pending)==nil)

reset()
fail_commit=true
denied,reason=restore.run(mock_uci)
assert(not denied and reason:find("staged changes reverted"))
assert(count_ops("commit")==1 and count_ops("revert")==1)
assert(committed.log_remote==nil and next(pending)==nil)

reset()
fail_set="log_port";fail_revert=true
denied,reason=restore.run(mock_uci)
assert(not denied and reason:find("revert could not be verified"))
assert(count_ops("revert")==1)
assert(committed.log_remote==nil)
assert(next(pending)~=nil)

print("BOOTS_RESTORE_ISOLATED_PASS")
