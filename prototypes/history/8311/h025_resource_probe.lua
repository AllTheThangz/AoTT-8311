-- H-025 direct-hardware preflight source model.
-- Fixed read-only paths and H-011 native wrapper via injected provider.
-- No timer, service, flash write, network call or production admission.
local native=require "8311.history_native_probe"
local M={}
local MEM_PATH="/proc/meminfo"
local CPU_PATH="/proc/stat"
local SELF_PATH="/proc/self/status"
local LOAD_PATH="/proc/loadavg"
local TEMP_PATH="/sys/class/thermal/thermal_zone0/temp"
local PATH_LIMITS={
    [MEM_PATH]=3072,[CPU_PATH]=3072,[SELF_PATH]=4096,
    [LOAD_PATH]=120,[TEMP_PATH]=48,
}

local function finite(value,low,high)
    return type(value)=="number" and value==value and
       value~=math.huge and value~=-math.huge and
       value>=low and value<=high
end
local function integer(value,low,high)
    return finite(value,low,high) and value==math.floor(value)
end
local function safe_read(provider,path)
    local maximum=PATH_LIMITS[path]
    if not maximum then return nil end
    local ok,output=pcall(provider.read,path,maximum)
    if not ok or type(output)~="string" or #output>maximum or
       output:find("[%z\1-\8\11\12\14-\31\127]") then return nil end
    return output
end
local function keyed(raw,name)
    if type(raw)~="string" then return nil end
    local found=nil
    for line in (raw.."\n"):gmatch("(.-)\n") do
        local key,digits=line:match("^([%a_]+):%s*(%d+)%s*kB%s*$")
        if key==name then
            if found~=nil or #digits>10 then return nil end
            found=tonumber(digits)
        end
    end
    if integer(found,0,4194304) then return found end
end
local function memory(raw)
    local total=keyed(raw,"MemTotal")
    local available=keyed(raw,"MemAvailable")
    if not integer(total,16384,4194304) or
       not integer(available,0,total) then return nil end
    return total,available
end
local function resident(raw)
    local rss=keyed(raw,"VmRSS")
    if integer(rss,0,4194304) then return rss end
end
local function load1(raw)
    if type(raw)~="string" then return nil end
    local field=raw:match("^%s*(%d+%.%d+)%s+%d+%.%d+%s+%d+%.%d+%s+")
    if not field then return nil end
    local n=tonumber(field)
    if finite(n,0,1000) then return n end
end
local function temperature(raw)
    if type(raw)~="string" then return nil end
    local value=raw:match("^%s*(%d+)%s*$")
    if not value or #value>6 then return nil end
    local n=tonumber(value)
    if integer(n,0,125000) then return n end
end
local function cpu_times(raw)
    if type(raw)~="string" then return nil end
    local line=raw:match("^([^ \n]+[^\n]*)")
    if not line or line:sub(1,4)~="cpu " then return nil end
    local count,values=0,{}
    for word in line:gmatch("%S+") do
        if count>0 then
            if not word:match("^%d+$") or #word>15 then return nil end
            local value=tonumber(word)
            if not integer(value,0,9007199254740991) then return nil end
            values[#values+1]=value
        end
        count=count+1
    end
    if #values<4 or #values>10 then return nil end
    local total=0
    for _,v in ipairs(values) do total=total+v end
    local idle=values[4]+(values[5] or 0)
    if not integer(total,0,9007199254740991) then return nil end
    return {total=total,idle=idle}
end
local function cpu_fraction(before,after)
    if not before or not after then return nil end
    local total=after.total-before.total
    local idle=after.idle-before.idle
    if not integer(total,1,1000000000) or
       not integer(idle,0,total) then return nil end
    return (total-idle)/total
end
local function opt(state)
    return state and "observed" or "unavailable"
end

-- All readings are internal source inputs. A caller-provided, synthetic
-- provider is never a target-issuer approval or a hardware qualification.
function M.capture_once(provider,mode)
    if mode~="offline_synthetic" then return nil,"direct_target_not_authorized" end
    if type(provider)~="table" or
       type(provider.read)~="function" or
       type(provider.run)~="function" then
        return nil,"invalid_readonly_provider"
    end
    local cpu_before=cpu_times(safe_read(provider,CPU_PATH))
    local snapshot,availability=native.read_once(provider)
    if not snapshot then return nil,availability end
    local cpu_after=cpu_times(safe_read(provider,CPU_PATH))
    local total,free=memory(safe_read(provider,MEM_PATH))
    local rss=resident(safe_read(provider,SELF_PATH))
    local load=load1(safe_read(provider,LOAD_PATH))
    local temp=temperature(safe_read(provider,TEMP_PATH))

    local output={
        schema=1,source="h025_injected_readonly_provider",
        provenance="offline_synthetic_unattested",
        hardware_qualified=false,
        approved_for_service_start=false,
        direct_management_authorization_verified=false,
        device_modified=false,
        firmware_bank_modified=false,
        network_reachability_proven=false,
        subscriber_wan_throughput_proven=false,
        native_observation_window_seconds=availability.observation_window_seconds,
        pon_observation=availability.pon,
        host_link_observation=availability.host_link,
        host_counters_observation=availability.host_counters,
        source_interface="eth0_0",
        cpu_busy_fraction=cpu_fraction(cpu_before,cpu_after),
        mem_total_kib=total,
        mem_available_kib=free,
        current_process_rss_kib=rss,
        load_average_1min=load,
        thermal_zone0_millidegc=temp,
        cpu_sample_status=opt(cpu_fraction(cpu_before,cpu_after)),
        memory_sample_status=opt(total and free),
        process_memory_status=opt(rss),
        temperature_sample_status=opt(temp),
        actual_pon_state=snapshot.pon_state,
        observed_host_link_mbps=snapshot.ethernet_mbps,
        boot_epoch_identity_exported=false,
        raw_eth_counters_exported=false,
        raw_shell_output_exported=false,
        measured_on_production_board=false,
    }
    -- No identity, MAC, serial, boot UUID, address or raw command data.
    return output
end
return M
