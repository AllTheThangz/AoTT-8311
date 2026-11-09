-- AoTT-8311 V3 persistent access/server rollback store.
local nixio=require "nixio"
local fs=require "nixio.fs"
local web=require "8311.webutil"
local M={}

local ROOT="/ptconf/8311/aott-recovery/v1/access"
local PARENT="/ptconf/8311/aott-recovery/v1"
local FILES={
    dropbear={path=ROOT.."/dropbear.before",max=65536},
    uhttpd={path=ROOT.."/uhttpd.before",max=65536},
    luci={path=ROOT.."/luci.before",max=65536},
}
local MARKER=ROOT.."/pending"
local CONFIRM=ROOT.."/confirmed"

local function valid_job(id)
    return type(id)=="string" and #id==32 and not id:find("[^0-9a-f]")
end
local function private_dir(st,mode)
    return type(st)=="table" and st.type=="dir" and st.uid==0 and st.gid==0 and st.modedec==mode
end
local function private_file(st,max)
    return type(st)=="table" and st.type=="reg" and st.uid==0 and st.gid==0 and
        st.modedec==600 and st.nlink==1 and type(st.size)=="number" and st.size>=1 and st.size<=max
end
local function close(fd)
    if not fd then return true end
    local ok,v=pcall(function() return fd:close() end)
    return ok and v~=false and v~=nil
end
local function sync_dir(path)
    local fd=nixio.open(path,nixio.open_flags("rdonly"))
    if not fd then return false end
    local ok=fd:sync()==true
    return close(fd) and ok
end
local function ensure_dir(path,mode)
    local st=fs.lstat(path)
    if not st then
        if not fs.mkdir(path,mode) then return false end
        st=fs.lstat(path)
    end
    return private_dir(st,mode)
end
local function ensure_tree()
    local base=fs.lstat("/ptconf/8311")
    if not base or base.type~="dir" or base.uid~=0 then return nil,"access_recovery_ancestor_unavailable" end
    if not ensure_dir("/ptconf/8311/aott-recovery",700) or
       not ensure_dir(PARENT,700) or not ensure_dir(ROOT,700) then
        return nil,"access_recovery_directory_unsafe"
    end
    return true
end
local function digest(path)
    local code,out,overflow=web.capture({"/usr/bin/sha256sum",path},256)
    local hash=type(out)=="string" and out:match("^([0-9a-f]+)%s")
    return code==0 and not overflow and hash and #hash==64 and hash or nil
end
local function atomic(path,data,max)
    if type(data)~="string" or #data<1 or #data>max or data:find("%z") then
        return nil,"access_recovery_content_invalid"
    end
    local old=fs.lstat(path)
    if old and not private_file(old,max) then return nil,"access_recovery_existing_file_unsafe" end
    local stage=path..".new."..tostring(nixio.getpid())
    if fs.lstat(stage) then return nil,"access_recovery_stage_exists" end
    local fd=nixio.open(stage,nixio.open_flags("wronly","creat","excl"),600)
    if not fd then return nil,"access_recovery_stage_create_failed" end
    local wrote=fd:writeall(data)
    local synced=wrote==#data and fd:sync()==true
    local closed=close(fd)
    if not synced or not closed then fs.unlink(stage);return nil,"access_recovery_stage_write_failed" end
    if not fs.rename(stage,path) then fs.unlink(stage);return nil,"access_recovery_replace_failed" end
    if fs.readfile(path,max+1)~=data or not sync_dir(ROOT) then
        return nil,"access_recovery_readback_failed"
    end
    return true
end
local function unlink(path,max)
    local st=fs.lstat(path)
    if not st then return true end
    return private_file(st,max) and fs.unlink(path)==true
end
local function marker(job,hashes)
    return table.concat({
        "AOTT-ACCESS-PENDING-1","job="..job,
        "dropbear="..hashes.dropbear,"uhttpd="..hashes.uhttpd,
        "luci="..hashes.luci,""
    },"\n")
end
local function parse(raw)
    if type(raw)~="string" or #raw>512 then return nil end
    local job,d,u,l=raw:match(
        "^AOTT%-ACCESS%-PENDING%-1\njob=([0-9a-f]+)\ndropbear=([0-9a-f]+)\nuhttpd=([0-9a-f]+)\nluci=([0-9a-f]+)\n$")
    if not valid_job(job) or #d~=64 or #u~=64 or #l~=64 then return nil end
    return {job_id=job,dropbear_sha256=d,uhttpd_sha256=u,luci_sha256=l}
end
local function backups(mark)
    local out={}
    for _,pkg in ipairs({"dropbear","uhttpd","luci"}) do
        local spec=FILES[pkg]
        local st=fs.lstat(spec.path)
        if not private_file(st,spec.max) or digest(spec.path)~=mark[pkg.."_sha256"] then
            return nil,"access_recovery_backup_invalid_"..pkg
        end
        local raw=fs.readfile(spec.path,spec.max+1)
        if type(raw)~="string" or #raw~=st.size then return nil,"access_recovery_backup_read_failed" end
        out[pkg]=raw
    end
    return out
end

function M.arm(job,raw)
    if not valid_job(job) or type(raw)~="table" then return nil,"access_recovery_scope_refused" end
    local ok,why=ensure_tree();if not ok then return nil,why end
    if fs.lstat(MARKER) then return nil,"access_recovery_already_pending" end
    if fs.lstat(CONFIRM) and not unlink(CONFIRM,512) then return nil,"access_confirmation_unsafe" end
    local hashes={}
    for _,pkg in ipairs({"dropbear","uhttpd","luci"}) do
        local spec=FILES[pkg]
        if fs.lstat(spec.path) and not unlink(spec.path,spec.max) then
            return nil,"access_recovery_stale_backup_unsafe"
        end
        ok,why=atomic(spec.path,raw[pkg],spec.max);if not ok then return nil,why end
        hashes[pkg]=digest(spec.path);if not hashes[pkg] then return nil,"access_recovery_digest_failed" end
    end
    ok,why=atomic(MARKER,marker(job,hashes),512);if not ok then return nil,why end
    local state=M.pending()
    if not state or state.job_id~=job then return nil,"access_recovery_arm_readback_failed" end
    return {status="ACCESS_RECOVERY_ARMED",job_id=job,contains_configuration_values=false}
end

function M.pending()
    local st=fs.lstat(MARKER)
    if not st then return {pending=false} end
    if not private_file(st,512) then return nil,"access_recovery_marker_unsafe" end
    local mark=parse(fs.readfile(MARKER,513))
    if not mark then return nil,"access_recovery_marker_invalid" end
    local data,why=backups(mark);if not data then return nil,why end
    mark.pending=true
    return mark
end
function M.load(job)
    if not valid_job(job) then return nil,"access_recovery_scope_refused" end
    local mark,why=M.pending();if not mark then return nil,why end
    if mark.pending~=true or mark.job_id~=job then return nil,"access_recovery_job_mismatch" end
    return backups(mark)
end
function M.confirm(job)
    if not valid_job(job) then return nil,"access_recovery_scope_refused" end
    local mark,why=M.pending();if not mark then return nil,why end
    if mark.pending~=true or mark.job_id~=job then return nil,"access_recovery_job_mismatch" end
    local content="AOTT-ACCESS-CONFIRMED-1\njob="..job.."\n"
    local st=fs.lstat(CONFIRM)
    if st then
        if private_file(st,512) and fs.readfile(CONFIRM,513)==content then
            return {status="ACCESS_CONFIRMATION_RECORDED",job_id=job}
        end
        return nil,"access_confirmation_mismatch"
    end
    local ok,ewhy=atomic(CONFIRM,content,512);if not ok then return nil,ewhy end
    return {status="ACCESS_CONFIRMATION_RECORDED",job_id=job}
end
function M.confirmed(job)
    if not valid_job(job) then return nil,"access_recovery_scope_refused" end
    local content="AOTT-ACCESS-CONFIRMED-1\njob="..job.."\n"
    local st=fs.lstat(CONFIRM)
    if not st then return false end
    if not private_file(st,512) then return nil,"access_confirmation_unsafe" end
    return fs.readfile(CONFIRM,513)==content or nil,
           fs.readfile(CONFIRM,513)==content and nil or "access_confirmation_mismatch"
end
function M.clear(job)
    local mark,why=M.pending();if not mark then return nil,why end
    if mark.pending~=true or mark.job_id~=job then return nil,"access_recovery_job_mismatch" end
    if not unlink(MARKER,512) or not sync_dir(ROOT) then return nil,"access_recovery_disarm_failed" end
    if not unlink(CONFIRM,512) then return nil,"access_confirmation_cleanup_failed" end
    for _,pkg in ipairs({"dropbear","uhttpd","luci"}) do
        local spec=FILES[pkg]
        if not unlink(spec.path,spec.max) then return nil,"access_recovery_cleanup_failed_"..pkg end
    end
    if not sync_dir(ROOT) then return nil,"access_recovery_cleanup_sync_failed" end
    return {status="ACCESS_RECOVERY_CLEARED",contains_configuration_values=false}
end

M.ROOT=ROOT
M.FILES=FILES
return M
