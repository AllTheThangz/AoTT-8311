-- AoTT-8311 V3 local volatile history handoff.
-- Fixed /run path, root-only files, dual kernel-lock freshness, no flash write.
local lock=require "8311.history_process_lock"
local gate=require "8311.history_publication_gate"
local exporter=require "8311.history_export"
local shape=require "8311.history_snapshot_shape"
local M={}
local DIR=lock.PRODUCTION_DIR
local FINAL=DIR.."/snapshot.json"
local STAGE=DIR.."/snapshot.json.new"
local MAX_BYTES=shape.MAX_BYTES

local function load()
    local ok,n,fs,json=pcall(function()
        return require "nixio",require "nixio.fs",require "luci.jsonc"
    end)
    if not ok then return nil,"history_runtime_modules_unavailable" end
    return {n=n,fs=fs,json=json}
end
local function dir_ok(st)
    return type(st)=="table" and st.type=="dir" and st.uid==0 and
        st.gid==0 and st.modedec==700
end
local function file_ok(st)
    return type(st)=="table" and st.type=="reg" and st.uid==0 and
        st.gid==0 and st.modedec==600 and st.nlink==1 and
        type(st.size)=="number" and st.size>=2 and st.size<=MAX_BYTES
end
local function same(a,b)
    return a and b and a.dev==b.dev and a.ino==b.ino
end
local function close(fd)
    if not fd then return true end
    local ok,result=pcall(function() return fd:close() end)
    return ok and result~=nil and result~=false
end
local function owner(handle)
    local status=lock.status(handle)
    return type(status)=="table" and status.cross_process_lock_held==true and
        status.production_runtime==true
end
local function decode(mods,body)
    if type(body)~="string" or #body<2 or #body>MAX_BYTES then
        return nil,"history_snapshot_size_invalid"
    end
    local ok,value=pcall(mods.json.parse,body)
    if not ok then return nil,"history_snapshot_json_invalid" end
    local valid,why=shape.validate(value)
    if not valid then return nil,why end
    if value.kind~="aott_local_history" or value.source_only_not_live~=false then
        return nil,"history_snapshot_not_local_runtime"
    end
    local canonical,reason=exporter.encode_checked_projection(value)
    if not canonical then return nil,reason end
    if canonical~=body then return nil,"history_snapshot_noncanonical" end
    return value
end
local function safe_unlink(fs,path)
    local st=fs.lstat(path)
    if not st then return true end
    if not file_ok(st) then return nil,"unsafe_history_snapshot_inode" end
    if not fs.unlink(path) or fs.lstat(path) then
        return nil,"history_snapshot_unlink_failed"
    end
    return true
end

function M.invalidate(handle)
    if not owner(handle) then return nil,"history_owner_required" end
    local mods,why=load(); if not mods then return nil,why end
    local dir=mods.fs.lstat(DIR)
    if not dir_ok(dir) then return nil,"unsafe_history_runtime_directory" end
    local ok,reason=safe_unlink(mods.fs,STAGE)
    if not ok then return nil,reason end
    ok,reason=safe_unlink(mods.fs,FINAL)
    if not ok then return nil,reason end
    return {status="history_runtime_snapshot_invalidated"}
end

function M.publish(handle,state)
    if not owner(handle) then return nil,"history_owner_required" end
    local mods,why=load(); if not mods then return nil,why end
    local n,fs=mods.n,mods.fs
    local dir=fs.lstat(DIR)
    if not dir_ok(dir) then return nil,"unsafe_history_runtime_directory" end
    local body,reason=exporter.export_json(state,"hour",100,"local_runtime")
    if not body then return nil,reason end
    local valid,invalid=decode(mods,body)
    if not valid then return nil,invalid end
    if fs.lstat(STAGE) then return nil,"stale_history_stage_present" end
    local fd=n.open(STAGE,n.open_flags("rdwr","creat","excl"),600)
    if not fd then return nil,"history_stage_create_failed" end
    local opened=fd:stat()
    if type(opened)~="table" or opened.type~="reg" or opened.uid~=0 or
       opened.gid~=0 or opened.modedec~=600 or opened.nlink~=1 then
        close(fd); return nil,"history_stage_identity_invalid"
    end
    local ok,wrote=pcall(function() return fd:writeall(body) end)
    if not ok or wrote~=#body then close(fd); return nil,"history_stage_write_failed" end
    local synced,done=pcall(function() return fd:sync() end)
    if not synced or done~=true or not close(fd) then
        return nil,"history_stage_sync_failed"
    end
    local staged=fs.lstat(STAGE)
    if not file_ok(staged) or not same(opened,staged) or not same(dir,fs.lstat(DIR)) then
        return nil,"history_stage_changed"
    end
    local old=fs.lstat(FINAL)
    if old and not file_ok(old) then return nil,"unsafe_history_target_inode" end
    if not fs.rename(STAGE,FINAL) then return nil,"history_snapshot_rename_failed" end
    local readback,read_why=M.read_unlocked()
    if readback~=body then return nil,read_why or "history_snapshot_readback_failed" end
    return {status="history_runtime_snapshot_verified",bytes=#body}
end

function M.read_unlocked()
    local mods,why=load(); if not mods then return nil,why end
    local n,fs=mods.n,mods.fs
    local dir=fs.lstat(DIR)
    if not dir_ok(dir) then return nil,"unsafe_history_runtime_directory" end
    local before=fs.lstat(FINAL)
    if not file_ok(before) then return nil,"history_snapshot_unavailable" end
    local fd=n.open(FINAL,"r")
    if not fd then return nil,"history_snapshot_open_failed" end
    local opened=fd:stat()
    if not file_ok(opened) or not same(before,opened) then
        close(fd); return nil,"history_snapshot_inode_changed"
    end
    local body=fd:readall(MAX_BYTES+1)
    local after=fs.lstat(FINAL)
    if not close(fd) or not file_ok(after) or not same(before,after) or
       not same(dir,fs.lstat(DIR)) then
        return nil,"history_snapshot_readback_unverified"
    end
    local valid,invalid=decode(mods,body)
    if not valid then return nil,invalid end
    return body,{status="history_runtime_snapshot_read",bytes=#body}
end

function M.admit()
    return gate.admit_writer(DIR,"production_runtime")
end
function M.revoke(handle)
    return gate.revoke_writer(handle)
end

function M.read_guarded()
    local held,why=lock.writer_present(DIR)
    if held~=true then return nil,why or "history_worker_not_running" end
    local admitted,gate_why=gate.reader_admitted(DIR,"production_runtime")
    if admitted~=true then return nil,gate_why or "history_snapshot_not_admitted" end
    local body,info=M.read_unlocked()
    if not body then return nil,info end
    local admitted_after,gate_after=gate.reader_admitted(DIR,"production_runtime")
    if admitted_after~=true then return nil,gate_after or "history_publisher_lost" end
    local held_after,lock_after=lock.writer_present(DIR)
    if held_after~=true then return nil,lock_after or "history_worker_lost" end
    info.guard_owner_checked_before_and_after=true
    info.publication_gate_checked_before_and_after=true
    return body,info
end

M.DIRECTORY=DIR
M.MAX_BYTES=MAX_BYTES
return M
