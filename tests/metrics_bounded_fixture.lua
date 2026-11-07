-- Synthetic bounded PON sampling, using the real AoTT tools module.
-- No real PON process, device, network, or files are accessed.
local module_path=assert(arg[1], "Provide the tools module")
local mode="success"
local subprocess_count=0
local legacy_count=0

package.preload["luci.util"]=function()
    return {
        exec=function(command)
            assert(command=="pon psg")
            legacy_count=legacy_count+1
            return "current=51"
        end
    }
end
package.preload["luci.sys"]=function() return {} end
package.preload["nixio.fs"]=function()
    return {readfile=function(path)
        if path=="/sys/class/thermal/thermal_zone0/temp" then return "41000" end
        if path=="/sys/class/thermal/thermal_zone1/temp" then return "42000" end
        return nil
    end}
end
package.preload["8311.webutil"]=function()
    return {capture=function(argv, maximum)
        subprocess_count=subprocess_count+1
        assert(maximum==1024)
        local expected={"/usr/bin/timeout","-k","1","3","/usr/bin/pon","psg"}
        assert(#argv==#expected)
        for k,v in ipairs(expected) do assert(argv[k]==v) end
        if mode=="success" then return 0,"current=51",false end
        if mode=="failure" then return 124,"",false end
        if mode=="overflow" then return 0,"current=51",true end
        error("Synthetic subprocess exception")
    end}
end

assert(loadfile(module_path))()
local tools=assert(package.loaded["8311.tools"])
local ok=tools.metrics(true)
assert(ok.ploam_state==51)
assert(ok.cpu1_tempC==41 and ok.cpu2_tempC==42)
assert(subprocess_count==1 and legacy_count==0)
for _, state in ipairs({"failure","overflow","exception"}) do
    mode=state
    local report=tools.metrics(true)
    assert(report.ploam_state==nil, "Missing metric should not be zero")
    assert(report.cpu1_tempC==41)
end
assert(subprocess_count==4 and legacy_count==0)
local original=tools.metrics()
assert(original.ploam_state==51)
assert(legacy_count==1 and subprocess_count==4)
print("BOUNDED_METRICS_FIXTURE_PASS")
