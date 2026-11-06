-- C-014 single-use native staging workspace. Offline synthetic paths only.
-- Holds one stable fcntl lock across candidate reads, mutations and verification.
-- Pending/failed/completed workspaces are never automatically reused or promoted.
local M={}
local TOKENS=setmetatable({}, {__mode="k"})
local HELD={}
local ERROR_TAG={}
local LOCK="stage.lock"
local STATE="stage.state"
local TEMP="stage.state.new"
local PENDING="AOTT-C014-SOURCE-STAGING-1\npending\n"
local VALIDATED="AOTT-C014-SOURCE-STAGING-1\nvalidated\n"
local function fail(code) error({tag=ERROR_TAG,code=code},0) end
local function reason(problem)
    if type(problem)=="table" and rawget(problem,"tag")==ERROR_TAG then
        return rawget(problem,"code")
    end
    return "staging_internal_error"
end
local function permitted(path,mode)
    if mode~="offline_synthetic" or type(path)~="string" then return false end
    local suffix=path:match("^/var/tmp/aott%-c014%-stage%-test%-([a-f0-9]+)$")
    return suffix~=nil and #suffix==16
end
local function directory_ok(st)
    return type(st)=="table" and st.type=="dir" and st.uid==0 and
        st.gid==0 and st.modedec==700
end
local function file_ok(st,limit)
    return type(st)=="table" and st.type=="reg" and st.uid==0 and
        st.gid==0 and st.modedec==600 and st.nlink==1 and
        type(st.size)=="number" and st.size>=0 and st.size<=limit
end
local function same(a,b)
    return a and b and a.ino~=nil and a["dev"]~=nil and
        a.ino==b.ino and a["dev"]==b["dev"]
end
local function close(fd)
    if not fd then return true end
    local ok,result=pcall(function() return fd:close() end)
    return ok and result==true
end
local function stat_optional(fs,path)
    local st,errno=fs.lstat(path)
    if st then return st end
    if errno~=2 then fail("staging_path_unavailable") end
    return nil
end
local function sync_directory(p)
    local fd=p.n.open(p.directory,p.n.open_flags("rdonly"))
    if not fd then fail("staging_directory_open_failed") end
    local ok,result=pcall(function()
        local st=fd:stat()
        if not directory_ok(st) or not same(st,p.parent) then fail("staging_directory_changed") end
        return fd:sync()
    end)
    local closed=close(fd)
    if not ok or result~=true or not closed then fail("staging_directory_sync_failed") end
end
local function owned(p)
    if p.n.getpid()~=p.pid then fail("staging_process_changed") end
    local parent=p.fs.lstat(p.directory)
    local visible=p.fs.lstat(p.directory.."/"..LOCK)
    local opened=p.fd:stat()
    if not directory_ok(parent) or not same(parent,p.parent) then fail("staging_directory_changed") end
    if not file_ok(visible,0) or not file_ok(opened,0) or
       not same(visible,p.lock) or not same(opened,p.lock) then
        fail("staging_lock_identity_changed")
    end
end
local function token(handle)
    local p=type(handle)=="table" and TOKENS[handle]
    if not p or HELD[p.directory]~=handle then fail("invalid_staging_handle") end
    owned(p)
    return p
end
local function read_state(p,expected)
    owned(p)
    local path=p.directory.."/"..STATE
    local before=p.fs.lstat(path)
    if not file_ok(before,128) or not same(before,p.marker) then fail("staging_marker_changed") end
    local fd=p.n.open(path,p.n.open_flags("rdonly"))
    if not fd then fail("staging_marker_open_failed") end
    local ok,bytes=pcall(function()
        local current=fd:stat()
        if not file_ok(current,128) or not same(current,before) then fail("staging_marker_changed") end
        local data=fd:read(129)
        local after=p.fs.lstat(path)
        if not file_ok(after,128) or not same(after,before) or data~=expected then
            fail("staging_marker_changed")
        end
        return data
    end)
    local closed=close(fd)
    if not ok then fail(reason(bytes)) end
    if not closed or bytes~=expected then fail("staging_marker_readback_failed") end
    owned(p)
end
local function checked(p)
    owned(p)
    if stat_optional(p.fs,p.directory.."/"..TEMP) then fail("staging_incomplete_marker") end
    read_state(p,PENDING)
end
local function write_state(p,bytes)
    owned(p)
    local final=p.directory.."/"..STATE
    local temporary=p.directory.."/"..TEMP
    if stat_optional(p.fs,temporary) then fail("staging_incomplete_marker") end
    if p.marker then read_state(p,PENDING)
    elseif stat_optional(p.fs,final) then fail("staging_workspace_already_used") end
    local fd=p.n.open(temporary,p.n.open_flags("wronly","creat","excl"),600)
    if not fd then fail("staging_marker_create_failed") end
    local ok,result=pcall(function()
        local before=fd:stat()
        if not file_ok(before,128) or not same(before,p.fs.lstat(temporary)) then
            fail("staging_marker_inode_invalid")
        end
        if fd:writeall(bytes)~=#bytes or fd:sync()~=true then fail("staging_marker_sync_failed") end
        local after=fd:stat()
        if not file_ok(after,128) or after.size~=#bytes or
           not same(before,after) or not same(after,p.fs.lstat(temporary)) then
            fail("staging_marker_changed")
        end
        return after
    end)
    local closed=close(fd)
    if not ok then fail(reason(result)) end
    if not closed then fail("staging_marker_close_failed") end
    owned(p)
    if p.marker then read_state(p,PENDING)
    elseif stat_optional(p.fs,final) then fail("staging_workspace_already_used") end
    local staged=p.fs.lstat(temporary)
    if not file_ok(staged,128) or not same(staged,result) then fail("staging_marker_changed") end
    if p.fs.rename(temporary,final)~=true then fail("staging_marker_replace_failed") end
    p.marker=result
    sync_directory(p)
    read_state(p,bytes)
end

function M.acquire(directory,mode)
    if not permitted(directory,mode) then return nil,"disallowed_staging_workspace" end
    -- POSIX process locks can be lost by closing a second descriptor for the
    -- same inode. Reject recursive entry BEFORE opening another descriptor.
    if HELD[directory] then return nil,"staging_already_owned_in_process" end
    local fd
    local ok,result=pcall(function()
        local n,fs=require "nixio",require "nixio.fs"
        local parent=fs.lstat(directory)
        if not directory_ok(parent) then fail("unsafe_staging_directory") end
        local path=directory.."/"..LOCK
        local before=stat_optional(fs,path)
        if before and not file_ok(before,0) then fail("unsafe_staging_lock") end
        fd=n.open(path,before and n.open_flags("rdwr") or n.open_flags("rdwr","creat","excl"),600)
        if not fd then fail("staging_lock_open_failed") end
        local opened=fd:stat()
        local visible=fs.lstat(path)
        if not file_ok(opened,0) or not file_ok(visible,0) or not same(opened,visible) or
           (before and not same(before,visible)) or not same(parent,fs.lstat(directory)) then
            fail("staging_lock_identity_changed")
        end
        local acquired,errno=fd:lock("tlock")
        if acquired~=true then
            if errno==11 or errno==13 then fail("staging_owned_by_other_process") end
            fail("staging_lock_unavailable")
        end
        local p={n=n,fs=fs,fd=fd,directory=directory,parent=parent,lock=opened,
                 pid=n.getpid(),used=false,busy=false,phase="unused"}
        owned(p)
        -- Do not read, trust, delete or resume a previous marker. A new
        -- workspace is required even after a validated candidate or crash.
        if stat_optional(fs,directory.."/"..STATE) or stat_optional(fs,directory.."/"..TEMP) then
            fail("staging_workspace_already_used")
        end
        if not before then
            if fd:sync()~=true then fail("staging_lock_sync_failed") end
            sync_directory(p)
        end
        owned(p)
        return p
    end)
    if not ok then
        if not close(fd) then
            -- Quarantine this process/path if descriptor release is uncertain.
            HELD[directory]={quarantined=true}
            return nil,"staging_close_unverified"
        end
        return nil,reason(result)
    end
    local handle={}
    TOKENS[handle]=result
    HELD[directory]=handle
    return handle,{status="SOURCE_STAGING_OWNER_ACQUIRED",source_only_not_deployed=true,
        exclusive_kernel_owner=true,lock_file_never_unlinked=true,no_live_apply=true}
end

function M.status(handle)
    local ok,p=pcall(token,handle)
    if not ok then return nil,reason(p) end
    if p.phase=="pending" or p.phase=="validated" then
        local checked,why=pcall(read_state,p,p.phase=="pending" and PENDING or VALIDATED)
        if not checked then return nil,reason(why) end
    end
    return {status="SOURCE_STAGING_OWNED",phase=p.phase,in_progress=p.busy,
        workspace_consumed=p.used,source_only_not_deployed=true,no_live_apply=true}
end

function M.stage(handle,plan,adapter,mode)
    if mode~="offline_synthetic" then return nil,"staging_mode_not_authorized" end
    local ok,p=pcall(token,handle)
    if not ok then return nil,reason(p) end
    if p.busy then return nil,"staging_in_progress" end
    if p.used then return nil,"staging_workspace_already_used" end
    if type(adapter)~="table" or getmetatable(adapter)~=nil or
       adapter.disposable_fixture~=true or adapter.workspace_directory~=p.directory or
       type(adapter.snapshot)~="function" or type(adapter.persisted_snapshot)~="function" or
       type(adapter.command)~="function" then return nil,"private_workspace_adapter_required" end
    p.busy=true;p.used=true;p.phase="unverified"
    local outcome,receipt=pcall(function()
        write_state(p,PENDING);p.phase="pending"
        local boundary_error
        local function invoke(fn,...)
            local valid,why=pcall(checked,p)
            if not valid then boundary_error=reason(why);fail(boundary_error) end
            local result=fn(...)
            valid,why=pcall(checked,p)
            if not valid then boundary_error=reason(why);fail(boundary_error) end
            return result
        end
        local wrapped={disposable_fixture=true,
            snapshot=function() return invoke(adapter.snapshot) end,
            persisted_snapshot=function() return invoke(adapter.persisted_snapshot) end,
            command=function(op) return invoke(adapter.command,op) end}
        local core=require "8311.vlan_transition"
        local result,why=core.verify_staged(plan,wrapped,mode)
        if boundary_error then fail(boundary_error) end
        -- A callback may throw after noticing ownership loss. Recheck even
        -- failed core calls, without reflecting the callback's exception.
        checked(p)
        if not result then fail("staging_candidate_rejected") end
        if result.status~="SOURCE_LUA_UCI_CANDIDATE_VALIDATED" or result.live_promote_available~=false or
           result.contains_configuration_values~=false then fail("staging_result_unverified") end
        checked(p)
        write_state(p,VALIDATED);p.phase="validated"
        return {status="SOURCE_LOCKED_UCI_CANDIDATE_VALIDATED",
            operations_checked=result.operations_checked,source_only_not_deployed=true,
            workspace_reusable=false,no_live_apply=true,no_configuration_values_exported=true,
            physical_recovery_and_power_loss_unqualified=true}
    end)
    p.busy=false
    if not outcome then return nil,reason(receipt) end
    return receipt
end

function M.close(handle)
    local p=type(handle)=="table" and TOKENS[handle]
    if not p or HELD[p.directory]~=handle then return nil,"invalid_staging_handle" end
    if p.n.getpid()~=p.pid then return nil,"staging_process_changed" end
    if p.busy then return nil,"staging_in_progress" end
    -- Release even if the pathname was altered. Never unlink the lock or
    -- markers; an interrupted candidate remains blocked after process exit.
    if not close(p.fd) then return nil,"staging_close_unverified" end
    TOKENS[handle]=nil;HELD[p.directory]=nil
    return {status="SOURCE_STAGING_OWNER_RELEASED",lock_file_never_unlinked=true,
        candidate_not_promoted=true,source_only_not_deployed=true}
end
return M
