-- AoTT-8311 V3 host-visible virtual SFP EEPROM verifier.
-- Fixed field map only. Reads the virtual EEPROM character device and never
-- touches PON subscriber identity or the physical EEPROM source.
local nixio=require "nixio"
local fs=require "nixio.fs"
local web=require "8311.webutil"
local M={}

local MAP={
    sfp_vendor={option="vendor_name",offset=20,length=16,kind="text"},
    sfp_oui={option="vendor_oui",offset=37,length=3,kind="oui"},
    sfp_partno={option="vendor_partno",offset=40,length=16,kind="text"},
    sfp_rev={option="vendor_rev",offset=56,length=4,kind="text"},
    sfp_serial={option="serial_no",offset=68,length=16,kind="text"},
    sfp_date={option="datecode",offset=84,length=8,kind="text"},
    sfp_vendordata={option="vendor_data",offset=96,length=32,kind="text"},
}

local function normalize_text(raw)
    if type(raw)~="string" then return nil end
    raw=raw:gsub("%z+$",""):gsub("%s+$","")
    if raw:find("[%z\1-\31\127]") then return nil end
    return raw
end

local function read_range(offset,length,adapter)
    if adapter and type(adapter.read_range)=="function" then
        return adapter.read_range(offset,length)
    end
    local st=fs.lstat("/dev/sfp_eeprom0")
    if not st or st.type~="chr" then return nil,"virtual_sfp_eeprom_unavailable" end
    local code,out,overflow=web.capture({
        "/bin/dd","if=/dev/sfp_eeprom0","bs=1",
        "skip="..tostring(offset),"count="..tostring(length)
    },length+16)
    if code~=0 or overflow or type(out)~="string" or #out~=length then
        return nil,"virtual_sfp_eeprom_read_failed"
    end
    return out
end

local function decode(spec,raw)
    if spec.kind=="text" then return normalize_text(raw) end
    if spec.kind=="oui" then
        if type(raw)~="string" or #raw~=3 then return nil end
        local hex=nixio.bin.hexlify(raw)
        if type(hex)~="string" or #hex~=6 then return nil end
        return (hex:sub(1,2)..":"..hex:sub(3,4)..":"..hex:sub(5,6)):upper()
    end
end

function M.read(id,adapter)
    local spec=MAP[id]
    if not spec then return nil,"unknown_sfp_field" end
    local raw,why=read_range(spec.offset,spec.length,adapter)
    if not raw then return nil,why end
    local value=decode(spec,raw)
    if value==nil then return nil,"virtual_sfp_eeprom_decode_failed" end
    return value
end

function M.matches(id,expected,adapter)
    local actual,why=M.read(id,adapter)
    if actual==nil then return nil,nil,why end
    if type(expected)~="string" then return false,actual,"virtual_sfp_eeprom" end
    local wanted=expected
    if id=="sfp_oui" then wanted=wanted:upper() end
    return actual==wanted,actual,"virtual_sfp_eeprom"
end

function M.option(id)
    local spec=MAP[id]
    return spec and spec.option or nil
end

function M.ids()
    local out={}
    for _,id in ipairs({
        "sfp_vendor","sfp_oui","sfp_partno","sfp_rev",
        "sfp_serial","sfp_date","sfp_vendordata"
    }) do out[#out+1]=id end
    return out
end

return M
