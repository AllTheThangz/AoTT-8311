-- AoTT-8311 C-011: bounded read-only advanced system / GPIO probe.
-- Only eight fixed noncredential environment names. Never returns
-- PON registration secrets, login hashes, raw environment dumps,
-- custom bootcmd, GPIO writes, or unbounded command output.
local M={}
local model=require "8311.effective_hardware_state"

local function trim(v,n)
    if type(v)~="string" or #v>(n or 128)+2 then return nil end
    v=v:gsub("[\r\n]+$","")
    if #v>(n or 128) or v:find("[%z\1-\31\127]") then return nil end
    return v
end

function M.capture(adapter)
    if type(adapter)~="table" or
       type(adapter.environment)~="function" or
       type(adapter.optic_dg_dis)~="function" or
       type(adapter.gpio)~="function" or
       type(adapter.link_speed)~="function" or
       type(adapter.rx_los_daemon)~="function" then
        return nil,"invalid_readonly_hardware_adapter"
    end
    local function safe(fn,...)
        local good,value=pcall(fn,...)
        return good and value or nil
    end
    local saved={}
    for _,id in ipairs(model.fields) do
        local raw=safe(adapter.environment,id,model.base_environment[id]==true)
        saved[id]=trim(raw,id=="ethtool_speed" and 100 or 128)
    end
    local config={
        optic_dg_dis=trim(safe(adapter.optic_dg_dis),8)
    }
    local gpio={}
    for _,number in ipairs({"508","510","505"}) do
        local rec=safe(adapter.gpio,number)
        if type(rec)=="table" then
            gpio[number]={
                value=trim(rec.value,8),
                direction=trim(rec.direction,8)
            }
        end
    end
    local runtime={
        gpio=gpio,
        link_speed_mbps=trim(safe(adapter.link_speed),16),
        rx_los_daemon=safe(adapter.rx_los_daemon),
    }
    return model.inspect(saved,config,runtime)
end

-- Authenticated LuCI GET only. No inputs are accepted from the request.
function M.live_hardware()
    local success,result=pcall(function()
        local fs=require "nixio.fs"
        local web=require "8311.webutil"
        local uci=require("luci.model.uci").cursor()
        local allowed={}
        for _,id in ipairs(model.fields) do allowed[id]=true end
        local function bounded(argv,maxbytes)
            local code,output,overflow=web.capture(argv,maxbytes)
            if code==0 and not overflow and type(output)=="string" then
                return output
            end
        end
        local adapter={
            environment=function(id,base)
                if not allowed[id] then return nil end
                local args={"/usr/bin/timeout","-k","1","3",
                            "/usr/sbin/fwenv_get"}
                if not base then args[#args+1]="--8311" end
                args[#args+1]=id
                return bounded(args,id=="ethtool_speed" and 128 or 192)
            end,
            optic_dg_dis=function()
                return uci:get("optic","common","dg_dis")
            end,
            gpio=function(n)
                if n~="508" and n~="510" and n~="505" then
                    return nil
                end
                local path="/sys/class/gpio/gpio"..n
                return {
                    value=fs.readfile(path.."/value",8),
                    direction=fs.readfile(path.."/direction",8),
                }
            end,
            link_speed=function()
                return fs.readfile("/sys/class/net/eth0_0/speed",24)
            end,
            rx_los_daemon=function()
                local code,output,overflow=web.capture({
                    "/usr/bin/timeout","-k","1","2",
                    "/bin/pidof","8311-rx_los.sh"},128)
                if code==0 and not overflow and
                   type(output)=="string" and output:match("%d") then
                    return true
                end
                if code==1 then return false end
                return nil
            end
        }
        return M.capture(adapter)
    end)
    if not success or type(result)~="table" or result.schema~=1 then
        return nil,"read_only_hardware_probe_unavailable"
    end
    return result
end

return M
