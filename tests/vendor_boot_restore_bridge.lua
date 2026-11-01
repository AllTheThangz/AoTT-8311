-- Test-only bridge between the actual r8 Lua restore logic and vendor UCI CLI.
-- All requests are synthetic and confined by the calling harness to a
-- disposable configuration directory. No real device is contacted.
local restore_file = assert(arg[1], "restore module path")
local no_record = arg[2] == "missing"
local mode = arg[2] or "normal"
local record = {
    schema=1, log_remote="1", log_ip="collector.example.com",
    log_port="5514", log_proto="tcp", aott_metrics="1",
    aott_metrics_client="192" .. ".0.2.40",
    aott_metrics_sha256=string.rep("a",64),
}
package.preload["8311.monitor_store"] = function()
    return {
        read=function() return not no_record and record or nil end,
        valid=function(v) return v==record end,
    }
end
package.preload["8311.webutil"] = function()
    return {capture=function() error("CLI bridge must be injected") end}
end
local restore = assert(loadfile(restore_file))()
local function callback(argv)
    assert(type(argv)=="table" and #argv>=7)
    assert(argv[1]=="/usr/bin/timeout" and argv[2]=="-k")
    assert(argv[3]=="1" and argv[4]=="3")
    assert(argv[5]=="/sbin/uci" and argv[6]=="-q")
    local action, param=argv[7],argv[8]
    assert(action=="get" or action=="set" or action=="commit" or
           action=="changes" or action=="revert")
    assert(param and not param:find("[\r\n\t]"))
    io.stdout:write("CMD\t" .. action .. "\t" .. param .. "\n")
    io.stdout:flush()
    local response = assert(io.stdin:read("*l"), "Harness closed")
    if response:sub(1,3)=="OK\t" then return response:sub(4) end
    assert(response=="ERR", "Unexpected harness response")
    return nil
end
local success, result=restore.run(callback)
local label=success and "OK" or "DENIED"
io.stdout:write("RESULT\t"..label.."\t"..tostring(result).."\n")
io.stdout:flush()
