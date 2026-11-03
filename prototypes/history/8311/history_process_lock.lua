-- H-022: root-owned advisory cross-process collector lock, source-only.
-- Uses the vendor's actual nixio library, with explicit trusted path policy.
-- No daemon, timer, HTTP endpoint, PON call or persistent history write.
local M={}
local HELD={}
local TOKENS=setmetatable({}, {__mode="k"})
local LOCK_BASENAME="collector.lock"
local PRODUCTION_DIR="/run/aott-history"

local function allowed(dir)
    if type(dir)~="string" or #dir<8 or #dir>110 then return false end
    if dir==PRODUCTION_DIR then return true end
    -- Strictly separated offline test root, never a configurable LuCI path.
    return dir:match("^/var/tmp/aott%-h022%-lock%-test%-[%w%-]+$")~=nil
end
local function secure_directory(st)
    return type(st)=="table" and st.type=="dir" and st.uid==0 and
           st.gid==0 and st.modedec==700
end
local function secure_file(st)
    return type(st)=="table" and st.type=="reg" and st.uid==0 and
           st.gid==0 and st.modedec==600 and st.nlink==1
end
local function same_object(a,b)
    return a and b and a["ino"]~=nil and a["dev"]~=nil and
           a["ino"]==b["ino"] and a["dev"]==b["dev"]
end
local function safe_close(fd)
    if fd then pcall(function() fd:close() end) end
end

-- The real kernel lock is a POSIX advisory fcntl lock. Its successful
-- acquisition is meaningful only if every collector uses the same path.
-- The vendor nixio ABI does not expose O_NOFOLLOW, so the parent directory
-- MUST be root-owned 0700 and independently provisioned, never world-writable.
function M.acquire(directory)
    if not allowed(directory) then return nil,"disallowed_lock_directory" end
    if HELD[directory] then return nil,"collector_already_owned_in_process" end
    local ok,nixio,fs=pcall(function()
        local n=require "nixio"
        return n,require "nixio.fs"
    end)
    if not ok or not nixio or not fs then
        return nil,"native_lock_library_unavailable"
    end
    local parent=fs.lstat(directory)
    if not secure_directory(parent) then
        return nil,"unsafe_collector_directory"
    end
    local path=directory.."/"..LOCK_BASENAME
    local existing=fs.lstat(path)
    if existing and not secure_file(existing) then
        return nil,"unsafe_lock_file"
    end
    local flags=existing and nixio.open_flags("rdwr")
        or nixio.open_flags("rdwr","creat","excl")
    local fd=nixio.open(path,flags,600)
    if not fd then
        return nil,existing and "lock_file_open_failed" or
            "lock_file_create_conflict"
    end
    local opened=fd:stat()
    local after=fs.lstat(path)
    if not secure_file(opened) or not secure_file(after) or
       not same_object(opened,after) or
       (existing and not same_object(existing,after)) or
       not secure_directory(fs.lstat(directory)) or
       not same_object(parent,fs.lstat(directory)) then
        safe_close(fd)
        return nil,"collector_lock_identity_changed"
    end
    -- A failed try-lock never waits and never starts a competing collector.
    local acquired=fd:lock("tlock")
    if not acquired then
        safe_close(fd)
        return nil,"collector_held_by_other_process"
    end
    local locked=fd:stat()
    local visible=fs.lstat(path)
    local final_parent=fs.lstat(directory)
    if not secure_file(locked) or not secure_file(visible) or
       not same_object(locked,visible) or
       not same_object(after,visible) or
       not secure_directory(final_parent) or
       not same_object(parent,final_parent) then
        safe_close(fd)
        return nil,"collector_lock_changed_after_acquire"
    end
    local handle={schema=1,source_only_not_deployed=true}
    TOKENS[handle]={fd=fd,directory=directory}
    HELD[directory]=handle
    return handle,{
        schema=1,status="advisory_owner_acquired",
        source_only_not_deployed=true,
        cross_process_fcntl_lock=true,
        lifetime="held_file_descriptor",
        lock_file_is_never_unlinked=true,
        no_pon_or_firmware_operation=true,
        filesystem_safety_not_hardware_qualified=true,
        no_device_setting_write=true,
    }
end

function M.release(handle)
    local private=type(handle)=="table" and TOKENS[handle]
    if not private or HELD[private.directory]~=handle then
        return nil,"invalid_collector_lock_handle"
    end
    -- Never unlink a lock file on release. Another process could already
    -- be opening or waiting on the stable inode, permitting split-brain.
    local ok,closed=pcall(function() return private.fd:close() end)
    if not ok or closed==false or closed==nil then
        return nil,"collector_lock_close_unverified"
    end
    TOKENS[handle]=nil
    HELD[private.directory]=nil
    return {
        status="advisory_owner_released",
        source_only_not_deployed=true,
        lock_file_is_never_unlinked=true,
        no_device_setting_write=true,
    }
end

function M.status(handle)
    local private=type(handle)=="table" and TOKENS[handle]
    if not private or HELD[private.directory]~=handle then
        return nil,"invalid_collector_lock_handle"
    end
    return {
        status="owned_in_this_process",
        source_only_not_deployed=true,
        must_keep_fd_open=true,
        cross_process_lock_held=true,
        no_pon_or_firmware_operation=true,
    }
end

-- H-027: passive kernel-owner evidence for a separate HTTP reader.
-- This never creates a lock file and never starts a collector. A possible
-- stale history file must not be served when its writer has crashed.
function M.writer_present(directory)
    if not allowed(directory) then return nil,"disallowed_lock_directory" end
    if HELD[directory] then
        return true,"owned_by_this_process"
    end
    local ok,nixio,fs=pcall(function()
        return require "nixio",require "nixio.fs"
    end)
    if not ok or not nixio or not fs then
        return nil,"native_lock_library_unavailable"
    end
    local parent=fs.lstat(directory)
    if not secure_directory(parent) then
        return nil,"unsafe_collector_directory"
    end
    local path=directory.."/"..LOCK_BASENAME
    local before=fs.lstat(path)
    if not secure_file(before) then return nil,"unsafe_lock_file" end
    local fd=nixio.open(path,nixio.open_flags("rdwr"))
    if not fd then return nil,"lock_file_open_failed" end
    local initial=fd:stat()
    if not secure_file(initial) or not same_object(before,initial) or
       not same_object(parent,fs.lstat(directory)) then
        safe_close(fd)
        return nil,"lock_file_identity_changed"
    end
    local acquired,errno=fd:lock("tlock")
    local after=fs.lstat(path)
    local final_parent=fs.lstat(directory)
    local safe=secure_file(after) and same_object(initial,after) and
        secure_directory(final_parent) and same_object(parent,final_parent)
    local closed,result=pcall(function() return fd:close() end)
    if not safe or not closed or result==false or result==nil then
        return nil,"lock_probe_unverified"
    end
    if acquired==true then
        -- No other process owns the lock, so the cache is not live.
        return false,"no_guarded_writer"
    end
    if acquired==false and (errno==11 or errno==13) then
        return true,"another_process_holds_fcntl_lock"
    end
    return nil,"indeterminate_lock_contention"
end

M.PRODUCTION_DIR=PRODUCTION_DIR
M.LOCK_BASENAME=LOCK_BASENAME
return M
