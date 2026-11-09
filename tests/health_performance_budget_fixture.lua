-- Synthetic telemetry budget test. Does not access any live ONU or device files.
local source = assert(arg[1], "health.lua path")
local calls, metrics_calls = {}, 0
local gem_status_ok = true
package.preload["nixio.fs"] = function()
    return {readfile=function(path, maxbytes)
        assert(maxbytes == 48 or maxbytes == 32)
        if path == "/proc/uptime" then return "100.0 1200.0" end
        if path == "/sys/class/net/eth0_0/speed" then return "10000" end
        error("Unexpected file read: "..path)
    end}
end
package.preload["luci.util"] = function() return {} end
package.preload["luci.model.uci"] = function() return {} end
package.preload["8311.tools"] = function()
    return {
        metrics=function(bounded)
            assert(bounded == true, "PON status should be bounded")
            metrics_calls=metrics_calls+1
            return {ploam_state=51, cpu1_tempC=50}
        end,
        is_finite=function(v)
            return type(v)=="number" and v==v and v~=math.huge
        end,
    }
end
package.preload["8311.webutil"] = function()
    return {capture=function(argv,limit)
        local cmd=table.concat(argv," ")
        calls[#calls+1]=cmd
        assert(cmd:find("/usr/bin/timeout",1,true)==1)
        if cmd:find("ethtool -S eth0_0",1,true) then
            assert(limit==16384)
            return 0, "RxGoodPkts: 100\nTxGoodPkts: 99\nRxGoodBytes: 5000\nTxGoodBytes: 4000\n", false
        end
        if cmd:find("GEM/XGEM Port Status",1,true) then
            assert(limit==16384)
            if not gem_status_ok then return 124,"",false end
            return 0,"1 513 1288 Active Internet 1518 On Bidirectional\n",false
        end
        if cmd:find("GEM/XGEM Port Counters",1,true) then
            assert(limit==16384)
            return 0,"1 513 9 90 8 80 0\n",false
        end
        error("unexpected command "..cmd)
    end}
end
local health = assert(loadfile(source))()
local basic = health.performance("basic")
assert(basic.schema==1)
assert(basic.gem_collection=="not_sampled" and basic.gem_ports==nil)
assert(basic.counters.RxGoodPkts==100)
assert(basic.optics.ploam_state==51)
assert(#calls==1 and metrics_calls==1, "basic mode must skip both GEM diagnostics")
local full = health.performance()
assert(full.gem_collection=="sampled" and #full.gem_ports==1)
assert(full.gem_ports[1].counters.us_packets==9)
assert(#calls==4 and metrics_calls==2, "default full mode remains compatible")
gem_status_ok=false
local absent=health.performance("full")
assert(absent.gem_ports==nil and absent.gem_collection=="sampled")
assert(#calls==6, "failed GEM status must not trigger second diagnostic")
print("AOTT_HEALTH_PERFORMANCE_BUDGET_PASS checks=12")
