-- AoTT-8311 V3 fixed-path live runtime helpers for advanced host controls.
-- No browser data reaches a shell. Every accepted ethtool token is parsed into
-- a fixed argv vector and all GPIO paths are constant.
local fs=require "nixio.fs"
local web=require "8311.webutil"
local M={}

local GPIO={
    console={number="510",path="/sys/class/gpio/gpio510"},
    dying={number="508",path="/sys/class/gpio/gpio508"},
}

local function bit(value)
    return value=="0" or value=="1"
end

local function gpio_ensure(spec)
    local st=fs.lstat(spec.path)
    if not st then
        if fs.writefile("/sys/class/gpio/export",spec.number)~=true then
            return nil,"gpio_export_failed"
        end
        st=fs.lstat(spec.path)
    end
    if not st or st.type~="dir" then return nil,"gpio_path_unavailable" end
    return true
end

local function gpio_apply(spec,high)
    local ok,why=gpio_ensure(spec)
    if not ok then return nil,why end
    local direction=high and "high" or "low"
    if fs.writefile(spec.path.."/direction",direction)~=true then
        return nil,"gpio_direction_write_failed"
    end
    local value=fs.readfile(spec.path.."/value",8)
    if type(value)~="string" then return nil,"gpio_value_read_failed" end
    value=value:gsub("[\r\n]+$","")
    local expected=high and "1" or "0"
    if value~=expected then return nil,"gpio_value_readback_mismatch" end
    return expected
end

local function gpio_value(spec)
    local st=fs.lstat(spec.path)
    if not st or st.type~="dir" then return nil,"gpio_path_unavailable" end
    local direction=fs.readfile(spec.path.."/direction",16)
    local value=fs.readfile(spec.path.."/value",8)
    if type(direction)~="string" or type(value)~="string" then
        return nil,"gpio_read_failed"
    end
    direction=direction:gsub("[\r\n]+$","")
    value=value:gsub("[\r\n]+$","")
    if direction~="out" or (value~="0" and value~="1") then
        return nil,"gpio_output_unqualified"
    end
    return value
end

function M.apply_console(value)
    if not bit(value) then return nil,"console_value_invalid" end
    return gpio_apply(GPIO.console,value=="1")
end

function M.console()
    local value,why=gpio_value(GPIO.console)
    if not value then return nil,why end
    return value
end

function M.apply_dying(value)
    if not bit(value) then return nil,"dying_gasp_value_invalid" end
    -- Enabled dying-gasp drives the shared RX pin low.
    local raw,why=gpio_apply(GPIO.dying,value=="0")
    if not raw then return nil,why end
    return raw=="0" and "1" or "0"
end

function M.dying()
    local value,why=gpio_value(GPIO.dying)
    if not value then return nil,why end
    return value=="0" and "1" or "0"
end

local ETHTOOL_ALLOWED={
    speed={["10"]=true,["100"]=true,["1000"]=true,["2500"]=true,
           ["5000"]=true,["10000"]=true},
    duplex={half=true,full=true},
    autoneg={on=true,off=true},
}
function M.parse_ethtool(value)
    if type(value)~="string" or #value>100 or
       value:find("[%z\1-\31\127]") then return nil,"ethtool_value_invalid" end
    if value=="" then return {},{} end
    local words={}
    for word in value:gmatch("%S+") do
        words[#words+1]=word
        if #words>6 then return nil,"ethtool_value_invalid" end
    end
    if #words%2~=0 then return nil,"ethtool_value_invalid" end
    local parsed,argv={}, {"/usr/sbin/ethtool","-s","eth0_0"}
    for i=1,#words,2 do
        local key,val=words[i],words[i+1]
        if parsed[key] or not ETHTOOL_ALLOWED[key] or not ETHTOOL_ALLOWED[key][val] then
            return nil,"ethtool_value_invalid"
        end
        parsed[key]=val
        argv[#argv+1]=key
        argv[#argv+1]=val
    end
    return parsed,argv
end

local function ethtool_status()
    local code,out,overflow=web.capture({"/usr/sbin/ethtool","eth0_0"},8192)
    if code~=0 or overflow or type(out)~="string" then
        return nil,"ethtool_status_unavailable"
    end
    local speed=out:match("\n%s*Speed:%s*(%d+)Mb/s")
    local duplex=out:match("\n%s*Duplex:%s*([A-Za-z]+)")
    local autoneg=out:match("\n%s*Auto%-negotiation:%s*([A-Za-z]+)")
    if not speed or not duplex or not autoneg then
        return nil,"ethtool_status_parse_failed"
    end
    duplex=duplex:lower()
    autoneg=autoneg:lower()
    if not ETHTOOL_ALLOWED.speed[speed] or not ETHTOOL_ALLOWED.duplex[duplex] or
       not ETHTOOL_ALLOWED.autoneg[autoneg] then
        return nil,"ethtool_status_unqualified"
    end
    return {speed=speed,duplex=duplex,autoneg=autoneg}
end

function M.current_ethtool()
    return ethtool_status()
end

function M.canonical_ethtool(record)
    if type(record)~="table" then return nil end
    local out={}
    for _,key in ipairs({"speed","duplex","autoneg"}) do
        local value=record[key]
        if value then out[#out+1]=key;out[#out+1]=value end
    end
    return table.concat(out," ")
end

function M.apply_ethtool(value)
    local parsed,argv=M.parse_ethtool(value)
    if not parsed then return nil,argv end
    if value=="" then return nil,"ethtool_clear_requires_reboot" end
    local code,_,overflow=web.capture(argv,2048)
    if code~=0 or overflow then return nil,"ethtool_apply_failed" end
    local now,why=ethtool_status()
    if not now then return nil,why end
    for key,expected in pairs(parsed) do
        if now[key]~=expected then return nil,"ethtool_readback_mismatch" end
    end
    return M.canonical_ethtool(now)
end

function M.ethtool_matches(value)
    local parsed,why=M.parse_ethtool(value)
    if not parsed then return nil,why end
    if value=="" then return nil,"ethtool_clear_runtime_pending" end
    local now,nwhy=ethtool_status()
    if not now then return nil,nwhy end
    for key,expected in pairs(parsed) do
        if now[key]~=expected then
            return false,M.canonical_ethtool(now),"ethtool_runtime_status"
        end
    end
    return true,M.canonical_ethtool(now),"ethtool_runtime_status"
end

return M
