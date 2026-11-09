-- AoTT-8311 V3 fixed-package PON/OMCI UCI transaction adapter.
local uci_lib=require "luci.model.uci"
local web=require "8311.webutil"
local fs=require "nixio.fs"
local M={}
local PACKAGES={gpon=true,omci=true,network=true}
local BACKUP_ROOT="/ptconf/8311/aott-recovery/v1/pon-config"

local function export(package)
    if not PACKAGES[package] then return nil,"pon_uci_package_refused" end
    local code,out,overflow=web.capture({"/sbin/uci","export",package},131072)
    if code~=0 or overflow or type(out)~="string" or #out<1 then
        return nil,"pon_uci_export_failed_"..package
    end
    return out
end

function M.snapshot()
    local out={}
    for _,pkg in ipairs({"gpon","omci","network"}) do
        local raw,why=export(pkg)
        if not raw then return nil,why end
        out[pkg]=raw
    end
    return out
end

local function value(records,id,default)
    local row=records[id]
    if type(row)~="table" then return default end
    if row.state=="value" then return row.value end
    return default
end

local function regid(hex)
    if type(hex)~="string" or #hex>72 or #hex%2~=0 or
       (hex~="" and not hex:match("^[0-9A-Fa-f]+$")) then return nil end
    if hex=="" then return nil end
    local bytes={}
    for i=1,#hex,2 do bytes[#bytes+1]=string.format("0x%s",hex:sub(i,i+1):upper()) end
    while #bytes<36 do bytes[#bytes+1]="0x00" end
    while #bytes>36 do table.remove(bytes) end
    return table.concat(bytes," ")
end

local function set_or_delete(cursor,pkg,section,option,v)
    if v==nil or v=="" then
        if cursor:get(pkg,section,option)==nil then return true end
        return cursor:delete(pkg,section,option)==true
    end
    return cursor:set(pkg,section,option,v)==true
end

function M.apply(records)
    if type(records)~="table" then return nil,"pon_uci_records_invalid" end
    local c=uci_lib.cursor()
    local warm=c:get("omci","default","warmstart") or "0"
    if warm~="0" then return nil,"pon_warmstart_unqualified_for_live_transaction" end

    local serial=value(records,"gpon_sn",nil)
    if serial and c:set("gpon","ploam","nSerial",serial)~=true then return nil,"pon_uci_gpon_serial_failed" end
    if not serial and c:get("gpon","ploam","nSerial")~=nil and
       c:delete("gpon","ploam","nSerial")~=true then return nil,"pon_uci_gpon_serial_clear_failed" end

    local rid=value(records,"reg_id_hex",nil)
    local encoded=rid and regid(rid) or nil
    if rid and not encoded then return nil,"pon_registration_id_invalid" end
    if encoded then
        if c:set("gpon","ploam","regID",encoded)~=true then return nil,"pon_uci_regid_failed" end
    elseif c:get("gpon","ploam","regID")~=nil and
           c:delete("gpon","ploam","regID")~=true then return nil,"pon_uci_regid_clear_failed" end

    if c:set("gpon","ponip","pon_mode",value(records,"pon_mode","xgspon"))~=true then return nil,"pon_uci_mode_failed" end
    if c:set("gpon","ponip","iop_mask",value(records,"iop_mask","18"))~=true then return nil,"pon_uci_iop_failed" end
    if c:set("omci","default","omcc_version",value(records,"omcc_version","0xA3"))~=true then return nil,"pon_uci_omcc_failed" end
    if c:set("omci","default","mib_file",value(records,"mib_file","/etc/mibs/prx300_1U.ini"))~=true then return nil,"pon_uci_mib_failed" end
    if not set_or_delete(c,"omci","default","loid",value(records,"loid",nil)) then return nil,"pon_uci_loid_failed" end
    if not set_or_delete(c,"omci","default","lpwd",value(records,"lpwd",nil)) then return nil,"pon_uci_lpwd_failed" end

    local mac=value(records,"iphost_mac",nil)
    if c:get("network","iphost1") then
        if not set_or_delete(c,"network","iphost1","macaddr",mac) then return nil,"pon_uci_iphost_mac_failed" end
    elseif mac then
        return nil,"pon_uci_iphost_section_unavailable"
    end

    for _,pkg in ipairs({"gpon","omci","network"}) do
        if c:commit(pkg)~=true then return nil,"pon_uci_commit_failed_"..pkg end
    end
    return M.verify(records)
end

function M.verify(records)
    local c=uci_lib.cursor()
    local function same(pkg,section,option,expected)
        local actual=c:get(pkg,section,option)
        if expected==nil or expected=="" then return actual==nil or actual=="" end
        return actual==expected
    end
    if not same("gpon","ploam","nSerial",value(records,"gpon_sn",nil)) then return nil,"pon_uci_serial_readback_mismatch" end
    local rid=value(records,"reg_id_hex",nil)
    if not same("gpon","ploam","regID",rid and regid(rid) or nil) then return nil,"pon_uci_regid_readback_mismatch" end
    if not same("gpon","ponip","pon_mode",value(records,"pon_mode","xgspon")) then return nil,"pon_uci_mode_readback_mismatch" end
    if not same("gpon","ponip","iop_mask",value(records,"iop_mask","18")) then return nil,"pon_uci_iop_readback_mismatch" end
    if not same("omci","default","omcc_version",value(records,"omcc_version","0xA3")) then return nil,"pon_uci_omcc_readback_mismatch" end
    if not same("omci","default","mib_file",value(records,"mib_file","/etc/mibs/prx300_1U.ini")) then return nil,"pon_uci_mib_readback_mismatch" end
    if not same("omci","default","loid",value(records,"loid",nil)) then return nil,"pon_uci_loid_readback_mismatch" end
    if not same("omci","default","lpwd",value(records,"lpwd",nil)) then return nil,"pon_uci_lpwd_readback_mismatch" end
    if c:get("network","iphost1") and
       not same("network","iphost1","macaddr",value(records,"iphost_mac",nil)) then
        return nil,"pon_uci_iphost_mac_readback_mismatch"
    end
    return {status="PON_UCI_VERIFIED",contains_configuration_values=false}
end

function M.restore()
    for _,pkg in ipairs({"gpon","omci","network"}) do
        local path=BACKUP_ROOT.."/"..pkg..".before"
        local expected=fs.readfile(path,131073)
        if type(expected)~="string" or #expected<1 or #expected>131072 then
            return nil,"pon_uci_restore_backup_unavailable_"..pkg
        end
        local code,_,overflow=web.capture({"/sbin/uci","-f",path,"import",pkg},4096)
        if code~=0 or overflow then return nil,"pon_uci_restore_import_failed_"..pkg end
        code,_,overflow=web.capture({"/sbin/uci","commit",pkg},4096)
        if code~=0 or overflow then return nil,"pon_uci_restore_commit_failed_"..pkg end
        local actual,why=export(pkg)
        if not actual or actual~=expected then
            return nil,why or "pon_uci_restore_readback_mismatch_"..pkg
        end
    end
    return {status="PON_UCI_RESTORED",contains_configuration_values=false}
end

M.regid=regid
return M
