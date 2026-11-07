-- AoTT-8311 V3 transactional activation for an already-validated local TLS candidate.
-- Fixed persistent paths, persistent rollback copy, detached confirmation window.
local nixio=require "nixio"
local fs=require "nixio.fs"
local web=require "8311.webutil"
local candidate=require "8311.tls_candidate"
local M={}

local PERSIST="/ptconf/8311/uhttpd"
local ACTIVE_CERT=PERSIST.."/uhttpd.crt"
local ACTIVE_KEY=PERSIST.."/uhttpd.key"
local PREV_CERT=PERSIST.."/.aott-prev.crt"
local PREV_KEY=PERSIST.."/.aott-prev.key"
local MARKER=PERSIST.."/.aott-tls-pending"
local CANDIDATE_CERT="/tmp/aott-tls-candidate/candidate.crt.der"
local CANDIDATE_KEY="/tmp/aott-tls-candidate/candidate.key.der"
local CONFIRM_NAME="tls-confirm"
local MAX=16384
local WAIT_TICKS=90

local function root_path(root,path)
    if root=="" then return path end
    return root..path
end
local function dir_ok(st)
    return type(st)=="table" and st.type=="dir" and st.uid==0 and st.gid==0 and st.modedec==700
end
local function file_ok(st,mode)
    return type(st)=="table" and st.type=="reg" and st.uid==0 and st.gid==0 and
        st.nlink==1 and st.modedec==mode and type(st.size)=="number" and
        st.size>=1 and st.size<=MAX
end
local function stage_ok(st,mode)
    return type(st)=="table" and st.type=="reg" and st.uid==0 and st.gid==0 and
        st.nlink==1 and st.modedec==mode and type(st.size)=="number" and
        st.size>=0 and st.size<=MAX
end
local function same(a,b)
    return a and b and a.dev==b.dev and a.ino==b.ino
end
local function close(fd)
    if not fd then return true end
    local ok,value=pcall(function() return fd:close() end)
    return ok and value~=nil and value~=false
end
local function valid_job(id)
    return type(id)=="string" and #id==32 and not id:find("[^0-9a-f]")
end
local function valid_sha(value)
    return type(value)=="string" and #value==64 and not value:find("[^0-9a-f]")
end
local function allowed(root,jobdir,mode)
    if mode=="production_runtime" then
        local id=type(jobdir)=="string" and jobdir:match("^/tmp/8311%-web%-jobs/([0-9a-f]+)$")
        return root=="" and valid_job(id)
    end
    local suffix=type(root)=="string" and
        root:match("^/var/tmp/aott%-tls%-activation%-test%-([0-9a-f]+)$")
    return mode=="offline_synthetic" and suffix and #suffix==16 and jobdir==root.."/job"
end
local function sync_dir(path)
    local fd=nixio.open(path,nixio.open_flags("rdonly"))
    if not fd then return nil end
    local ok=fd:sync()==true
    local closed=close(fd)
    return ok and closed
end
local function safe_unlink(path,mode)
    local st=fs.lstat(path)
    if not st then return true end
    if not file_ok(st,mode) then return nil end
    return fs.unlink(path)==true
end
local function safe_unlink_stage(path,mode)
    local st=fs.lstat(path)
    if not st then return true end
    if not stage_ok(st,mode) then return nil end
    return fs.unlink(path)==true
end
local function discard_stages(root)
    for _,entry in ipairs({
        {root_path(root,ACTIVE_CERT)..".new",644},
        {root_path(root,ACTIVE_KEY)..".new",600},
        {root_path(root,PREV_CERT)..".new",600},
        {root_path(root,PREV_KEY)..".new",600},
        {root_path(root,MARKER)..".new",600},
    }) do
        if not safe_unlink_stage(entry[1],entry[2]) then
            return nil,"tls_unsafe_staging_artifact"
        end
    end
    return true
end
local function copy_atomic(src,src_mode,dst,dst_mode,parent)
    local before=fs.lstat(src)
    if not file_ok(before,src_mode) then return nil,"tls_source_file_unsafe" end
    local current=fs.lstat(dst)
    if current and not file_ok(current,dst_mode) then return nil,"tls_destination_file_unsafe" end
    local stage=dst..".new"
    if fs.lstat(stage) then return nil,"tls_stale_stage_present" end
    local input=nixio.open(src,"r")
    if not input then return nil,"tls_source_open_failed" end
    local output
    local function abort(code)
        close(input)
        close(output)
        if not safe_unlink_stage(stage,dst_mode) then
            return nil,"tls_stage_cleanup_unverified"
        end
        return nil,code
    end
    local opened=input:stat()
    if not file_ok(opened,src_mode) or not same(before,opened) then
        return abort("tls_source_inode_changed")
    end
    output=nixio.open(stage,nixio.open_flags("wronly","creat","excl"),dst_mode)
    if not output then close(input); return nil,"tls_stage_create_failed" end
    local total=0
    while true do
        local chunk=input:read(4096)
        if type(chunk)~="string" then return abort("tls_source_read_failed") end
        if chunk=="" then break end
        total=total+#chunk
        if total>MAX or output:writeall(chunk)~=#chunk then
            return abort("tls_stage_write_failed")
        end
    end
    local source_after=fs.lstat(src)
    if total~=before.size or not file_ok(source_after,src_mode) or
       not same(before,source_after) then
        return abort("tls_source_changed")
    end
    if not close(input) then
        input=nil
        return abort("tls_source_close_failed")
    end
    input=nil
    if output:sync()~=true then return abort("tls_stage_sync_failed") end
    if not close(output) then
        output=nil
        if not safe_unlink_stage(stage,dst_mode) then
            return nil,"tls_stage_cleanup_unverified"
        end
        return nil,"tls_stage_close_failed"
    end
    output=nil
    local staged=fs.lstat(stage)
    if not file_ok(staged,dst_mode) or staged.size~=total then
        if not safe_unlink_stage(stage,dst_mode) then
            return nil,"tls_stage_cleanup_unverified"
        end
        return nil,"tls_stage_verification_failed"
    end
    if not fs.rename(stage,dst) then
        if not safe_unlink_stage(stage,dst_mode) then
            return nil,"tls_stage_cleanup_unverified"
        end
        return nil,"tls_atomic_replace_failed"
    end
    local final=fs.lstat(dst)
    if not file_ok(final,dst_mode) or final.size~=total or not sync_dir(parent) then
        return nil,"tls_replace_readback_failed"
    end
    return true
end
local function write_marker(root,jobid,fingerprint)
    local dir=root_path(root,PERSIST)
    local path=root_path(root,MARKER)
    if fs.lstat(path) then return nil,"tls_pending_marker_exists" end
    local data="AOTT-TLS-PENDING-1\njob="..jobid.."\ncandidate="..fingerprint.."\n"
    local stage=path..".new"
    if fs.lstat(stage) then return nil,"tls_pending_stage_exists" end
    local fd=nixio.open(stage,nixio.open_flags("wronly","creat","excl"),600)
    if not fd then return nil,"tls_pending_create_failed" end
    local wrote=fd:writeall(data)
    local synced=fd:sync()
    local closed=close(fd)
    if wrote~=#data or synced~=true or not closed then
        safe_unlink_stage(stage,600)
        return nil,"tls_pending_write_failed"
    end
    local st=fs.lstat(stage)
    if not file_ok(st,600) or st.size~=#data then
        safe_unlink_stage(stage,600)
        return nil,"tls_pending_stage_invalid"
    end
    if not fs.rename(stage,path) or not sync_dir(dir) then
        safe_unlink_stage(stage,600)
        return nil,"tls_pending_commit_failed"
    end
    return true
end
local function parse_marker(root)
    local path=root_path(root,MARKER)
    local st=fs.lstat(path)
    if not st then return {pending=false} end
    if not file_ok(st,600) or st.size>256 then return nil,"tls_pending_marker_unsafe" end
    local raw=fs.readfile(path,257)
    if type(raw)~="string" or #raw~=st.size then return nil,"tls_pending_read_failed" end
    local job,sha=raw:match("^AOTT%-TLS%-PENDING%-1\njob=([0-9a-f]+)\ncandidate=([0-9a-f]+)\n$")
    if not valid_job(job) or not valid_sha(sha) then return nil,"tls_pending_marker_invalid" end
    return {pending=true,job_id=job,certificate_sha256=sha}
end
local function cleanup_orphans(root)
    local pending,why=parse_marker(root)
    if not pending then return nil,why end
    if pending.pending then return true end
    local ok,reason=discard_stages(root)
    if not ok then return nil,reason end
    for _,entry in ipairs({
        {root_path(root,PREV_CERT),600},
        {root_path(root,PREV_KEY),600},
    }) do
        if not safe_unlink(entry[1],entry[2]) then
            return nil,"tls_unsafe_orphan_rollback_artifact"
        end
    end
    return true
end
local function confirm_present(jobdir)
    local path=jobdir.."/"..CONFIRM_NAME
    local st=fs.lstat(path)
    if not st then return false end
    if not file_ok(st,600) or st.size~=19 then return nil,"tls_confirm_marker_unsafe" end
    local raw=fs.readfile(path,20)
    if raw~="AOTT-TLS-CONFIRM-1\n" then return nil,"tls_confirm_marker_invalid" end
    return true
end
local function cleanup(root)
    local dir=root_path(root,PERSIST)
    for _,entry in ipairs({
        {root_path(root,MARKER),600},
        {root_path(root,PREV_CERT),600},
        {root_path(root,PREV_KEY),600},
    }) do
        local ok=safe_unlink(entry[1],entry[2])
        if not ok then return nil,"tls_cleanup_refused" end
    end
    if not sync_dir(dir) then return nil,"tls_cleanup_sync_failed" end
    return true
end
local function restore(root,provider,restart)
    local staged,stage_why=discard_stages(root)
    if not staged then return nil,stage_why end
    local dir=root_path(root,PERSIST)
    local prev_cert=root_path(root,PREV_CERT)
    local prev_key=root_path(root,PREV_KEY)
    if not file_ok(fs.lstat(prev_cert),600) or not file_ok(fs.lstat(prev_key),600) then
        return nil,"tls_rollback_backup_unavailable"
    end
    local ok,why=copy_atomic(prev_key,600,root_path(root,ACTIVE_KEY),600,dir)
    if not ok then return nil,why end
    ok,why=copy_atomic(prev_cert,600,root_path(root,ACTIVE_CERT),644,dir)
    if not ok then return nil,why end
    if restart and not provider.restart() then return nil,"tls_rollback_restart_failed" end
    local cleaned,clean_why=cleanup(root)
    if not cleaned then return nil,clean_why end
    return {status="rolled_back",active_https_changed=false,rollback_verified=true}
end
local function provider_ok(provider)
    return type(provider)=="table" and type(provider.digest)=="function" and
        type(provider.recovery_ready)=="function" and type(provider.restart)=="function" and
        type(provider.sleep)=="function"
end
local function transaction(root,jobdir,expected,mode,provider,wait_ticks)
    if not allowed(root,jobdir,mode) or not valid_sha(expected) or not provider_ok(provider) then
        return nil,"tls_activation_scope_refused"
    end
    local persist=root_path(root,PERSIST)
    local candidate_dir=root_path(root,"/tmp/aott-tls-candidate")
    if not dir_ok(fs.lstat(persist)) or not dir_ok(fs.lstat(candidate_dir)) or
       not dir_ok(fs.lstat(jobdir)) then return nil,"tls_activation_directory_unsafe" end
    local pending,pending_why=parse_marker(root)
    if not pending then return nil,pending_why end
    if pending.pending then return nil,"tls_activation_already_pending" end
    local cleaned,clean_why=cleanup_orphans(root)
    if not cleaned then return nil,clean_why end
    local active_cert=root_path(root,ACTIVE_CERT)
    local active_key=root_path(root,ACTIVE_KEY)
    local candidate_cert=root_path(root,CANDIDATE_CERT)
    local candidate_key=root_path(root,CANDIDATE_KEY)
    if not file_ok(fs.lstat(active_cert),644) or not file_ok(fs.lstat(active_key),600) then
        return nil,"tls_active_pair_unqualified"
    end
    if not file_ok(fs.lstat(candidate_cert),644) or not file_ok(fs.lstat(candidate_key),600) then
        return nil,"tls_candidate_pair_unqualified"
    end
    if provider.digest(candidate_cert)~=expected then return nil,"tls_candidate_fingerprint_changed" end
    if provider.recovery_ready()~=true then return nil,"tls_secondary_recovery_unavailable" end

    local ok,why=copy_atomic(active_cert,644,root_path(root,PREV_CERT),600,persist)
    if not ok then return nil,why end
    ok,why=copy_atomic(active_key,600,root_path(root,PREV_KEY),600,persist)
    if not ok then
        safe_unlink(root_path(root,PREV_CERT),600)
        return nil,why
    end
    local jobid=mode=="production_runtime" and jobdir:match("([0-9a-f]+)$") or string.rep("a",32)
    ok,why=write_marker(root,jobid,expected)
    if not ok then return nil,why end
    ok,why=copy_atomic(candidate_key,600,active_key,600,persist)
    if not ok then return restore(root,provider,false) end
    ok,why=copy_atomic(candidate_cert,644,active_cert,644,persist)
    if not ok then return restore(root,provider,false) end
    if not provider.restart() then return restore(root,provider,true) end

    for _=1,wait_ticks do
        local confirmed=confirm_present(jobdir)
        if confirmed==nil then return restore(root,provider,true) end
        if confirmed==true then
            local cleaned,clean_why=cleanup(root)
            if not cleaned then return nil,clean_why end
            return {status="confirmed",active_https_changed=true,rollback_verified=false}
        end
        provider.sleep()
    end
    return restore(root,provider,true)
end
local function production_provider()
    return {
        digest=function(path) return web.digest(path) end,
        recovery_ready=function()
            local a,_,ao=web.capture({"/usr/libexec/8311-root-credential-ready"},128)
            local b,_,bo=web.capture({"/bin/pidof","dropbear"},128)
            return a==0 and ao==false and b==0 and bo==false
        end,
        restart=function()
            local code,_,overflow=web.capture({"/etc/init.d/uhttpd","restart"},2048)
            return code==0 and overflow==false
        end,
        sleep=function() nixio.nanosleep(2,0) end,
    }
end

function M.pending()
    return parse_marker("")
end
function M.activate(jobdir,expected)
    local state,why=candidate.status()
    if not state or state.candidate_ready~=true or state.certificate_sha256~=expected then
        return nil,why or "tls_candidate_not_ready"
    end
    return transaction("",jobdir,expected,"production_runtime",production_provider(),WAIT_TICKS)
end
function M.recover_pending()
    local state,why=parse_marker("")
    if not state then return nil,why end
    if not state.pending then
        local cleaned,clean_why=cleanup_orphans("")
        if not cleaned then return nil,clean_why end
        return {status="no_pending_tls_activation",recovered=false}
    end
    local result,reason=restore("",production_provider(),false)
    if not result then return nil,reason end
    result.status="pending_tls_activation_recovered"
    result.recovered=true
    return result
end
function M.fixture_activate(root,jobdir,expected,provider,wait_ticks)
    return transaction(root,jobdir,expected,"offline_synthetic",provider,wait_ticks or 1)
end
function M.fixture_recover(root,provider)
    local state,why=parse_marker(root)
    if not state then return nil,why end
    if not state.pending then
        local cleaned,clean_why=cleanup_orphans(root)
        if not cleaned then return nil,clean_why end
        return {status="no_pending_tls_activation",recovered=false}
    end
    return restore(root,provider,false)
end
M.CONFIRM_NAME=CONFIRM_NAME
M.WAIT_SECONDS=WAIT_TICKS*2
M.PERSIST_DIRECTORY=PERSIST
return M
