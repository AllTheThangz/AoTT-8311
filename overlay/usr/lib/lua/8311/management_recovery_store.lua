-- AoTT-8311 V3 persistent management rollback store.
-- Fixed private paths only. The pending marker is committed last so boot recovery
-- never observes an armed transaction without complete, fsynced backups.
local nixio=require "nixio"
local fs=require "nixio.fs"
local web=require "8311.webutil"
local M={}

local PARENT="/ptconf/8311/aott-recovery"
local ROOT=PARENT.."/v1"
local DIR=ROOT.."/management"
local NETWORK=DIR.."/network.before"
local FIREWALL=DIR.."/firewall.before"
local ENVIRONMENT=DIR.."/environment.before"
local DROPBEAR=DIR.."/dropbear.before"
local MARKER=DIR.."/pending"
local CONFIRM=DIR.."/confirmed"
local MAX_UCI=65536
local MAX_ENV=4096

local function path(root,p)
    return root=="" and p or root..p
end
local function production_or_fixture(root,mode)
    if mode=="production_runtime" then return root=="" end
    return mode=="offline_synthetic" and type(root)=="string" and
        root:match("^/var/tmp/aott%-management%-recovery%-test%-[0-9a-f]+$")~=nil
end
local function valid_job(id)
    return type(id)=="string" and #id==32 and not id:find("[^0-9a-f]")
end
local function dir_ok(st,mode)
    return type(st)=="table" and st.type=="dir" and st.uid==0 and st.gid==0 and
        st.modedec==mode
end
local function file_ok(st,maximum)
    return type(st)=="table" and st.type=="reg" and st.uid==0 and st.gid==0 and
        st.modedec==600 and st.nlink==1 and type(st.size)=="number" and
        st.size>=1 and st.size<=maximum
end
local function close(fd)
    if not fd then return true end
    local ok,value=pcall(function() return fd:close() end)
    return ok and value~=false and value~=nil
end
local function sync_dir(p)
    local fd=nixio.open(p,nixio.open_flags("rdonly"))
    if not fd then return false end
    local ok=fd:sync()==true
    local closed=close(fd)
    return ok and closed
end
local function ensure_dir(p,mode)
    local st=fs.lstat(p)
    if not st then
        if not fs.mkdir(p,mode) then return false end
        st=fs.lstat(p)
    end
    return dir_ok(st,mode)
end
local function ensure_tree(root)
    local pt=path(root,"/ptconf")
    local base=path(root,"/ptconf/8311")
    local recovery_parent=path(root,PARENT)
    local recovery=path(root,ROOT)
    local dir=path(root,DIR)
    if root~="" then
        if not ensure_dir(pt,755) or not ensure_dir(base,755) then
            return nil,"management_recovery_fixture_ancestor_unsafe"
        end
    else
        local a,b=fs.lstat(pt),fs.lstat(base)
        if not a or not b or a.type~="dir" or b.type~="dir" or
           a.uid~=0 or b.uid~=0 then
            return nil,"management_recovery_ancestor_unavailable"
        end
    end
    if not ensure_dir(recovery_parent,700) or not ensure_dir(recovery,700) or
       not ensure_dir(dir,700) then
        return nil,"management_recovery_directory_unsafe"
    end
    return true
end
local function digest(p)
    local code,out,overflow=web.capture({"/usr/bin/sha256sum",p},256)
    if code~=0 or overflow or type(out)~="string" then return nil end
    local value=out:match("^([0-9a-f]+)%s")
    return value and #value==64 and value or nil
end
local function write_atomic(p,data,maximum)
    if type(data)~="string" or #data<1 or #data>maximum or
       data:find("%z") then return nil,"management_recovery_content_invalid" end
    local current=fs.lstat(p)
    if current and not file_ok(current,maximum) then
        return nil,"management_recovery_existing_file_unsafe"
    end
    local stage=p..".new."..tostring(nixio.getpid())
    if fs.lstat(stage) then return nil,"management_recovery_stage_exists" end
    local fd=nixio.open(stage,nixio.open_flags("wronly","creat","excl"),600)
    if not fd then return nil,"management_recovery_stage_create_failed" end
    local wrote=fd:writeall(data)
    local synced=wrote==#data and fd:sync()==true
    local closed=close(fd)
    if not synced or not closed then
        fs.unlink(stage)
        return nil,"management_recovery_stage_write_failed"
    end
    local staged=fs.lstat(stage)
    if not file_ok(staged,maximum) or staged.size~=#data then
        fs.unlink(stage)
        return nil,"management_recovery_stage_verify_failed"
    end
    if not fs.rename(stage,p) then
        fs.unlink(stage)
        return nil,"management_recovery_replace_failed"
    end
    local final=fs.lstat(p)
    if not file_ok(final,maximum) or final.size~=#data or
       not sync_dir(p:match("^(.*)/[^/]+$")) then
        return nil,"management_recovery_replace_readback_failed"
    end
    local read=fs.readfile(p,maximum+1)
    if read~=data then return nil,"management_recovery_content_readback_failed" end
    return true
end
local function safe_unlink(p,maximum)
    local st=fs.lstat(p)
    if not st then return true end
    if not file_ok(st,maximum) then return false end
    return fs.unlink(p)==true
end
local function marker_content(job,nh,fh,eh,dh)
    return table.concat({
        "AOTT-MANAGEMENT-PENDING-2",
        "job="..job,
        "network="..nh,
        "firewall="..fh,
        "environment="..eh,
        "dropbear="..dh,
        "",
    },"\n")
end
local function parse_marker(raw)
    if type(raw)~="string" or #raw>512 then return nil end
    local job,nh,fh,eh,dh=raw:match(
        "^AOTT%-MANAGEMENT%-PENDING%-2\njob=([0-9a-f]+)\nnetwork=([0-9a-f]+)\nfirewall=([0-9a-f]+)\nenvironment=([0-9a-f]+)\ndropbear=([0-9a-f]+)\n$")
    if not valid_job(job) or #nh~=64 or #fh~=64 or #eh~=64 or #dh~=64 then return nil end
    return {job_id=job,network_sha256=nh,firewall_sha256=fh,
            environment_sha256=eh,dropbear_sha256=dh}
end
local function read_backups(root,marker)
    local np,fp,ep,dp=path(root,NETWORK),path(root,FIREWALL),
        path(root,ENVIRONMENT),path(root,DROPBEAR)
    local ns,fs_,es,ds=fs.lstat(np),fs.lstat(fp),fs.lstat(ep),fs.lstat(dp)
    if not file_ok(ns,MAX_UCI) or not file_ok(fs_,MAX_UCI) or
       not file_ok(es,MAX_ENV) or not file_ok(ds,MAX_UCI) then
        return nil,"management_recovery_backup_unsafe"
    end
    if digest(np)~=marker.network_sha256 or digest(fp)~=marker.firewall_sha256 or
       digest(ep)~=marker.environment_sha256 or digest(dp)~=marker.dropbear_sha256 then
        return nil,"management_recovery_backup_digest_mismatch"
    end
    local n,f,e,d=fs.readfile(np,MAX_UCI+1),fs.readfile(fp,MAX_UCI+1),
        fs.readfile(ep,MAX_ENV+1),fs.readfile(dp,MAX_UCI+1)
    if type(n)~="string" or type(f)~="string" or type(e)~="string" or
       type(d)~="string" or #n~=ns.size or #f~=fs_.size or #e~=es.size or
       #d~=ds.size then
        return nil,"management_recovery_backup_read_failed"
    end
    return {network=n,firewall=f,environment=e,dropbear=d}
end

function M.arm(root,job,network,firewall,environment,dropbear,mode)
    if not production_or_fixture(root,mode) or not valid_job(job) then
        return nil,"management_recovery_scope_refused"
    end
    local ok,why=ensure_tree(root)
    if not ok then return nil,why end
    local marker=path(root,MARKER)
    if fs.lstat(marker) then return nil,"management_recovery_already_pending" end
    if fs.lstat(path(root,CONFIRM)) and
       not safe_unlink(path(root,CONFIRM),512) then
        return nil,"management_recovery_stale_confirmation_unsafe"
    end
    -- No stale private file may be reused as a new backup.
    for _,entry in ipairs({
        {path(root,NETWORK),MAX_UCI},{path(root,FIREWALL),MAX_UCI},
        {path(root,ENVIRONMENT),MAX_ENV},{path(root,DROPBEAR),MAX_UCI},
    }) do
        if fs.lstat(entry[1]) and not safe_unlink(entry[1],entry[2]) then
            return nil,"management_recovery_stale_backup_unsafe"
        end
    end
    local n,f,e,d=path(root,NETWORK),path(root,FIREWALL),
        path(root,ENVIRONMENT),path(root,DROPBEAR)
    ok,why=write_atomic(n,network,MAX_UCI); if not ok then return nil,why end
    ok,why=write_atomic(f,firewall,MAX_UCI); if not ok then return nil,why end
    ok,why=write_atomic(e,environment,MAX_ENV); if not ok then return nil,why end
    ok,why=write_atomic(d,dropbear,MAX_UCI); if not ok then return nil,why end
    local nh,fh,eh,dh=digest(n),digest(f),digest(e),digest(d)
    if not nh or not fh or not eh or not dh then return nil,"management_recovery_digest_failed" end
    local data=marker_content(job,nh,fh,eh,dh)
    ok,why=write_atomic(marker,data,512)
    if not ok then return nil,why end
    if not sync_dir(path(root,DIR)) then return nil,"management_recovery_marker_sync_failed" end
    local parsed=M.pending(root,mode)
    if not parsed or parsed.job_id~=job then
        return nil,"management_recovery_arm_readback_failed"
    end
    return {status="MANAGEMENT_RECOVERY_ARMED",job_id=job,
            contains_configuration_values=false}
end

function M.pending(root,mode)
    if not production_or_fixture(root,mode) then
        return nil,"management_recovery_scope_refused"
    end
    local p=path(root,MARKER)
    local st=fs.lstat(p)
    if not st then return {pending=false} end
    if not file_ok(st,512) then return nil,"management_recovery_marker_unsafe" end
    local raw=fs.readfile(p,513)
    local marker=parse_marker(raw)
    if not marker then return nil,"management_recovery_marker_invalid" end
    local backups,why=read_backups(root,marker)
    if not backups then return nil,why end
    marker.pending=true
    return marker
end

function M.load(root,job,mode)
    if not production_or_fixture(root,mode) or not valid_job(job) then
        return nil,"management_recovery_scope_refused"
    end
    local marker,why=M.pending(root,mode)
    if not marker then return nil,why end
    if marker.pending~=true or marker.job_id~=job then
        return nil,"management_recovery_job_mismatch"
    end
    return read_backups(root,marker)
end

function M.confirm(root,job,mode)
    if not production_or_fixture(root,mode) or not valid_job(job) then
        return nil,"management_recovery_scope_refused"
    end
    local marker,why=M.pending(root,mode)
    if not marker then return nil,why end
    if marker.pending~=true or marker.job_id~=job then
        return nil,"management_recovery_job_mismatch"
    end
    local p=path(root,CONFIRM)
    local existing=fs.lstat(p)
    if existing then
        if not file_ok(existing,512) then return nil,"management_confirmation_unsafe" end
        local raw=fs.readfile(p,513)
        if raw=="AOTT-MANAGEMENT-CONFIRMED-1\njob="..job.."\n" then
            return {status="MANAGEMENT_CONFIRMATION_RECORDED",job_id=job}
        end
        return nil,"management_confirmation_job_mismatch"
    end
    local ok,ewhy=write_atomic(p,"AOTT-MANAGEMENT-CONFIRMED-1\njob="..job.."\n",512)
    if not ok then return nil,ewhy end
    if not sync_dir(path(root,DIR)) then return nil,"management_confirmation_sync_failed" end
    return {status="MANAGEMENT_CONFIRMATION_RECORDED",job_id=job}
end

function M.confirmed(root,job,mode)
    if not production_or_fixture(root,mode) or not valid_job(job) then
        return nil,"management_recovery_scope_refused"
    end
    local p=path(root,CONFIRM)
    local st=fs.lstat(p)
    if not st then return false end
    if not file_ok(st,512) then return nil,"management_confirmation_unsafe" end
    local raw=fs.readfile(p,513)
    if raw=="AOTT-MANAGEMENT-CONFIRMED-1\njob="..job.."\n" then return true end
    return nil,"management_confirmation_job_mismatch"
end

function M.clear(root,job,mode)
    if not production_or_fixture(root,mode) or not valid_job(job) then
        return nil,"management_recovery_scope_refused"
    end
    local marker,why=M.pending(root,mode)
    if not marker then return nil,why end
    if marker.pending~=true or marker.job_id~=job then
        return nil,"management_recovery_job_mismatch"
    end
    -- Disarm first. If cleanup is interrupted, leftover backups are inert.
    if not safe_unlink(path(root,MARKER),512) or not sync_dir(path(root,DIR)) then
        return nil,"management_recovery_disarm_failed"
    end
    if not safe_unlink(path(root,CONFIRM),512) then
        return nil,"management_confirmation_cleanup_refused"
    end
    for _,entry in ipairs({
        {path(root,NETWORK),MAX_UCI},{path(root,FIREWALL),MAX_UCI},
        {path(root,ENVIRONMENT),MAX_ENV},{path(root,DROPBEAR),MAX_UCI},
    }) do
        if not safe_unlink(entry[1],entry[2]) then
            return nil,"management_recovery_cleanup_refused"
        end
    end
    if not sync_dir(path(root,DIR)) then return nil,"management_recovery_cleanup_sync_failed" end
    return {status="MANAGEMENT_RECOVERY_CLEARED",contains_configuration_values=false}
end

M.ROOT=ROOT
M.DIR=DIR
return M
