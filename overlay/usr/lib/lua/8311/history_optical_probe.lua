-- AoTT V3r4 optical/thermal history source adapter.
-- Fixed PRX126 EEPROM DDM bytes and thermal sensors, read-only, RAM-only.
-- Only decoded numeric measurements leave this module. The raw 106-byte
-- EEPROM block (which may contain other private fields) is never returned.
local M={}
local EEPROM="/sys/class/pon_mbox/pon_mbox0/device/eeprom51"
local THERMAL0="/sys/class/thermal/thermal_zone0/temp"
local THERMAL1="/sys/class/thermal/thermal_zone1/temp"

local function bounded(value,lo,hi)
    return type(value)=="number" and value==value and
        value~=math.huge and value~=-math.huge and
        value>=lo and value<=hi
end
local function word(bytes,n)
    return bytes:byte(n)*256 + bytes:byte(n+1)
end
local function dBm(w)
    if w==0 then return nil end
    local v=10*math.log10(w/10000)
    if bounded(v,-45,15) then return v end
end
function M.decode_eeprom(raw)
    if type(raw)~="string" or #raw<106 or #raw>106 then
        return nil,"optical_ddm_unavailable"
    end
    local values={}
    local temperature=word(raw,97)
    if temperature>=32768 then temperature=temperature-65536 end
    temperature=temperature/256
    if bounded(temperature,-40,110) then values.optic_temp_c=temperature end
    local voltage=word(raw,99)/10000
    if bounded(voltage,2.0,4.0) then values.module_voltage_v=voltage end
    local bias=word(raw,101)/500
    if bounded(bias,0,200) then values.tx_bias_ma=bias end
    local tx=dBm(word(raw,103))
    local rx=dBm(word(raw,105))
    if tx then values.tx_power_dbm=tx end
    if rx then values.rx_power_dbm=rx end
    return next(values) and values or nil,"optical_ddm_unavailable"
end
local function thermal(raw)
    if type(raw)~="string" or #raw>80 or
       not raw:match("^%s*%-?%d+%s*$") then return nil end
    local v=tonumber(raw)
    if not v then return nil end
    v=v/1000
    if bounded(v,-35,130) then return v end
end
function M.read_once(provider)
    if type(provider)~="table" or type(provider.read)~="function" then
        return nil,"invalid_optical_provider"
    end
    local function fixed(path,size)
        local ok,raw=pcall(provider.read,path,size)
        if not ok or type(raw)~="string" or #raw>size then return nil end
        return raw
    end
    local raw=fixed(EEPROM,106)
    local optics=raw and M.decode_eeprom(raw) or nil
    optics=optics or {}
    local cpu0=thermal(fixed(THERMAL0,80))
    local cpu1=thermal(fixed(THERMAL1,80))
    if cpu0 then optics.cpu0_temp_c=cpu0 end
    if cpu1 then optics.cpu1_temp_c=cpu1 end
    if not next(optics) then return nil,"optical_and_thermal_unavailable" end
    return optics,{
        optical_measurement_observed=optics.rx_power_dbm~=nil or
            optics.tx_power_dbm~=nil or optics.optic_temp_c~=nil,
        cpu_measurement_observed=cpu0~=nil or cpu1~=nil,
        no_device_write=true,
        no_raw_eeprom_export=true,
    }
end
M.paths={eeprom=EEPROM,cpu0=THERMAL0,cpu1=THERMAL1}
return M
