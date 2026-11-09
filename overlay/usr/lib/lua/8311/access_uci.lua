-- AoTT-8311 V3 fixed UCI writer for guarded access/server configuration.
local fs=require "nixio.fs"
local web=require "8311.webutil"
local uci_lib=require "luci.model.uci"
local config=require "8311.access_config"
local M={}

local PACKAGES={dropbear=true,uhttpd=true,luci=true}
local BACKUP_ROOT="/ptconf/8311/aott-recovery/v1/access"

local function export(package)
    if not PACKAGES[package] then return nil,"access_package_refused" end
    local code,out,overflow=web.capture({"/sbin/uci","export",package},65536)
    if code~=0 or overflow or type(out)~="string" or #out<1 or #out>65536 or out:find("%z") then
        return nil,"access_export_failed_"..package
    end
    return out
end

function M.raw_snapshot()
    local out={}
    for _,pkg in ipairs({"dropbear","uhttpd","luci"}) do
        local raw,why=export(pkg)
        if not raw then return nil,why end
        out[pkg]=raw
    end
    return out
end

local function unique_dropbear(cursor)
    local names={}
    cursor:foreach("dropbear","dropbear",function(row)
        if type(row)=="table" and type(row[".name"])=="string" then names[#names+1]=row[".name"] end
    end)
    if #names~=1 then return nil,"dropbear_section_not_unique" end
    return names[1]
end

local function bool_drop(value) return value=="1" and "1" or "0" end

function M.apply(snapshot,desired)
    if type(snapshot)~="table" or type(snapshot.management_ip)~="string" or
       type(desired)~="table" then return nil,"access_apply_inputs_invalid" end
    local cursor=uci_lib.cursor()
    local drop,why=unique_dropbear(cursor)
    if not drop then return nil,why end
    if drop~=snapshot.dropbear_section then return nil,"dropbear_section_changed" end

    for id,map in pairs(config.dropbear_map) do
        local value=desired[id]
        if value==nil then return nil,"access_desired_missing_"..id end
        if cursor:set("dropbear",drop,map[1],
            config.field_map[id].type=="bool" and bool_drop(value) or value)~=true then
            return nil,"dropbear_stage_failed_"..id
        end
    end
    if cursor:commit("dropbear")~=true then return nil,"dropbear_commit_failed" end

    for id,map in pairs(config.web_map) do
        local value=desired[id]
        if value==nil then return nil,"access_desired_missing_"..id end
        if cursor:set("uhttpd","main",map[1],value)~=true then
            return nil,"uhttpd_stage_failed_"..id
        end
    end
    local ip=snapshot.management_ip
    if cursor:delete("uhttpd","main","listen_http")~=true then
        -- Deleting an already absent list may be reported false by some UCI
        -- backends. Re-check instead of treating absence as a failed mutation.
        local current=cursor:get_list("uhttpd","main","listen_http")
        if type(current)=="table" and #current>0 then return nil,"uhttpd_http_listener_delete_failed" end
    end
    if desired.web_http_port~="" then
        if cursor:add_list("uhttpd","main","listen_http",ip..":"..desired.web_http_port)~=true then
            return nil,"uhttpd_http_listener_stage_failed"
        end
    end
    if cursor:delete("uhttpd","main","listen_https")~=true then
        local current=cursor:get_list("uhttpd","main","listen_https")
        if type(current)=="table" and #current>0 then return nil,"uhttpd_https_listener_delete_failed" end
    end
    if cursor:add_list("uhttpd","main","listen_https",ip..":"..desired.web_https_port)~=true then
        return nil,"uhttpd_https_listener_stage_failed"
    end
    if cursor:commit("uhttpd")~=true then return nil,"uhttpd_commit_failed" end

    if cursor:set("luci","sauth","sessiontime",desired.luci_sessiontime)~=true or
       cursor:commit("luci")~=true then return nil,"luci_session_commit_failed" end

    local after,after_why=config.snapshot()
    if not after then return nil,after_why end
    for _,field in ipairs(config.fields) do
        if after.values[field.id]~=desired[field.id] then
            return nil,"access_readback_mismatch_"..field.id
        end
    end
    if after.http_scope~=(desired.web_http_port=="" and "disabled" or "management_ipv4_only") or
       after.https_scope~="management_ipv4_only" then
        return nil,"access_listener_scope_readback_mismatch"
    end
    return {status="ACCESS_UCI_APPLIED_AND_READ_BACK",
            contains_configuration_values=false},after
end

function M.restore_package(package)
    if not PACKAGES[package] then return nil,"access_restore_package_refused" end
    local path=BACKUP_ROOT.."/"..package..".before"
    local st=fs.lstat(path)
    if not st or st.type~="reg" or st.uid~=0 or st.gid~=0 or
       st.modedec~=600 or st.nlink~=1 or type(st.size)~="number" or
       st.size<1 or st.size>65536 then return nil,"access_restore_file_unsafe" end
    local code,_,overflow=web.capture({"/sbin/uci","-f",path,"import",package},4096)
    if code~=0 or overflow then return nil,"access_restore_import_failed_"..package end
    code,_,overflow=web.capture({"/sbin/uci","commit",package},4096)
    if code~=0 or overflow then return nil,"access_restore_commit_failed_"..package end
    return true
end

function M.restore_all()
    for _,pkg in ipairs({"dropbear","uhttpd","luci"}) do
        local ok,why=M.restore_package(pkg)
        if not ok then return nil,why end
    end
    return true
end

M.backup_root=BACKUP_ROOT
return M
