-- H-028: independent, source-only publication admission lock.
-- Unlike collector.lock, publication.lock is held ONLY after a new,
-- bounded H-026 snapshot has been fully published and read back.
-- A new writer's main lock never makes its predecessor's cache readable.
-- Both locks are POSIX fcntl locks released on process exit/SIGKILL.
-- NOT installed, no procd, firmware, PON, network or flash operation.
local M={}
local NAME="publication.lock"
local HELD={}
local TOKENS=setmetatable({}, {__mode="k"})

local function allowed(directory,mode)
    return mode=="offline_synthetic" and type(directory)=="string" and
        #directory<=110 and
        directory:match("^/var/tmp/aott%-h022%-lock%-test%-[%w%-]+$")~=nil
end
local function dir_ok(st)
    return type(st)=="table" and st.type=="dir" and st.uid==0 and
        st.gid==0 and st.modedec==700 and
        type(st.dev)=="number" and type(st.ino)=="number"
end
local function file_ok(st)
    return type(st)=="table" and st.type=="reg" and st.uid==0 and
        st.gid==0 and st.modedec==600 and st.nlink==1 and
        type(st.dev)=="number" and type(st.ino)=="number" and
        st.size==0
end
local function same(a,b)
    return type(a)=="table" and type(b)=="table" and
        a["dev"]==b["dev"] and a["ino"]==b["ino"]
end
local function modules()
    local ok,n,fs=pcall(function()
        return require "nixio",require "nixio.fs"
    end)
    if not ok or type(n)~="table" or type(fs)~="table" then
        return nil,"vendor_publication_lock_library_unavailable"
    end
    return {n=n,fs=fs}
end
local function close(fd)
    local ok,result=pcall(function()return fd:close()end)
    return ok and result~=nil and result~=false
end

-- Explicit acquisition *only after* the caller has verified a new
-- snapshot. The fixed protected file is never deleted, including when
-- the process dies or another collector attempts to start.
function M.admit_writer(directory,mode)
    if not allowed(directory,mode) then
        return nil,"publication_gate_not_authorized"
    end
    if HELD[directory] then return nil,"publication_gate_already_held" end
    local mods,why=modules()
    if not mods then return nil,why end
    local fs,n=mods.fs,mods.n
    local parent=fs.lstat(directory)
    if not dir_ok(parent) then return nil,"unsafe_publication_directory" end
    local path=directory.."/"..NAME
    local before=fs.lstat(path)
    if before and not file_ok(before) then
        return nil,"unsafe_publication_inode"
    end
    local flags=before and n.open_flags("rdwr") or
        n.open_flags("rdwr","creat","excl")
    local fd=n.open(path,flags,600)
    if not fd then return nil,"publication_gate_open_failed" end
    local initial=fd:stat()
    local visible=fs.lstat(path)
    if not file_ok(initial) or not file_ok(visible) or
       not same(initial,visible) or
       (before and not same(before,visible)) or
       not dir_ok(fs.lstat(directory)) or
       not same(parent,fs.lstat(directory)) then
        close(fd)
        return nil,"publication_gate_inode_changed"
    end
    local locked=fd:lock("tlock")
    if locked~=true then
        close(fd)
        return nil,"publication_gate_held_by_other_process"
    end
    local after=fs.lstat(path)
    if not file_ok(fd:stat()) or not file_ok(after) or
       not same(initial,after) or
       not same(parent,fs.lstat(directory)) then
        close(fd)
        return nil,"publication_gate_changed_after_lock"
    end
    local token=[REDACTED]
    TOKENS[token]={fd=fd,directory=directory}
    HELD[directory]=token
    return token,{status="verified_snapshot_admitted",
        source_only_not_deployed=true,no_onu_or_network_io=true}
end

function M.revoke_writer(token)
    local held=type(token)=="table" and TOKENS[token]
    if not held or HELD[held.directory]~=token then
        return nil,"invalid_publication_gate_handle"
    end
    if not close(held.fd) then return nil,"publication_gate_close_unverified" end
    TOKENS[token]=nil
    HELD[held.directory]=nil
    return {status="publication_admission_revoked",
        source_only_not_deployed=true,no_snapshot_deleted=true}
end

-- Separate HTTP-side admission check: no creation, no wait, no
-- foreground native counter read and no trust in a leftover lock file.
function M.reader_admitted(directory,mode)
    if not allowed(directory,mode) then
        return nil,"publication_gate_not_authorized"
    end
    if HELD[directory] then return true,"same_process_publisher" end
    local mods,why=modules()
    if not mods then return nil,why end
    local fs,n=mods.fs,mods.n
    local parent=fs.lstat(directory)
    if not dir_ok(parent) then return nil,"unsafe_publication_directory" end
    local path=directory.."/"..NAME
    local before=fs.lstat(path)
    if not file_ok(before) then return nil,"publication_gate_missing_or_unsafe" end
    local fd=n.open(path,n.open_flags("rdwr"))
    if not fd then return nil,"publication_gate_read_open_failed" end
    local opened=fd:stat()
    if not file_ok(opened) or not same(before,opened) or
       not same(parent,fs.lstat(directory)) then
        close(fd)
        return nil,"publication_gate_read_inode_changed"
    end
    local acquired,errno=fd:lock("tlock")
    local after=fs.lstat(path)
    local safe=file_ok(after) and same(opened,after) and
        dir_ok(fs.lstat(directory)) and same(parent,fs.lstat(directory))
    local closed=close(fd)
    if not safe or not closed then
        return nil,"publication_gate_probe_unverified"
    end
    if acquired==true then return false,"no_verified_publisher" end
    if acquired==false and (errno==11 or errno==13) then
        return true,"verified_publisher_lock_present"
    end
    return nil,"publication_gate_contention_ambiguous"
end

M.NAME=NAME
return M
