-- H-026: OFFLINE-ONLY, volatile, bounded H-016 snapshot handoff.
-- Uses real vendor MIPS nixio and luci.jsonc in isolated test directories.
-- No live LuCI route, daemon, external address, NAND or firmware overlay.
local guarded=require "8311.history_guarded_collector"
local shape=require "8311.history_snapshot_shape"
local canonical=require "8311.history_export"
local M={}
local DIR_PATTERN="^/var/tmp/aott%-h026%-ipc%-test%-%w+$"
local FINAL_NAME="snapshot.json"
local STAGE_NAME="snapshot.json.new"
local MAX_BYTES=shape.MAX_BYTES

local function permitted(path,mode)
    return mode=="offline_synthetic" and type(path)=="string" and
        #path<120 and path:match(DIR_PATTERN)~=nil
end
local function dir_ok(st)
    return type(st)=="table" and st.type=="dir" and st.uid==0 and
        st.gid==0 and st.modedec==700 and
        type(st.dev)=="number" and type(st.ino)=="number"
end
local function file_ok(st)
    return type(st)=="table" and st.type=="reg" and st.uid==0 and
        st.gid==0 and st.modedec==600 and st.nlink==1 and
        type(st.size)=="number" and st.size>=0 and
        st.size<=MAX_BYTES
end
local function same(a,b)
    return type(a)=="table" and type(b)=="table" and
        a["dev"]==b["dev"] and a["ino"]==b["ino"]
end
local function load_fs()
    local ok,n,fs,j=pcall(function()
        return require "nixio",require "nixio.fs",require "luci.jsonc"
    end)
    if not ok or type(n)~="table" or type(fs)~="table" or
       type(j)~="table" or type(j.parse)~="function" then
        return nil,"offline_vendor_modules_unavailable"
    end
    return {n=n,fs=fs,json=j}
end
local function decode(json,payload)
    if type(payload)~="string" or #payload<2 or
       #payload>MAX_BYTES then return nil,"invalid_snapshot_bytes" end
    local ok,value=pcall(json.parse,payload)
    if not ok then return nil,"invalid_snapshot_json" end
    local good,why=shape.validate(value)
    if not good then return nil,why end
    local rebuilt,reason=canonical.encode_checked_projection(value)
    if not rebuilt then return nil,reason end
    if rebuilt~=payload then return nil,"noncanonical_snapshot_bytes" end
    return true
end
local function owner(handle)
    local ok,receipt=pcall(guarded.status,handle)
    return ok and type(receipt)=="table" and
        receipt.exclusive_kernel_owner==true and
        receipt.source_only_not_deployed==true
end
local function close(fd)
    if not fd then return true end
    local ok,value=pcall(function() return fd:close() end)
    return ok and value~=false and value~=nil
end
local function trusted_dir(fs,path)
    local st=fs.lstat(path)
    return dir_ok(st) and st or nil
end
local function existing_ok(fs,path)
    local st=fs.lstat(path)
    if st and not file_ok(st) then return nil,"unsafe_snapshot_inode" end
    return st or false
end

function M.read(directory,mode)
    if not permitted(directory,mode) then
        return nil,"snapshot_read_not_authorized"
    end
    local mods,why=load_fs()
    if not mods then return nil,why end
    local fs,n=mods.fs,mods.n
    local dir=trusted_dir(fs,directory)
    if not dir then return nil,"unsafe_snapshot_directory" end
    local path=directory.."/"..FINAL_NAME
    local state,reason=existing_ok(fs,path)
    if state==nil then return nil,reason end
    if state==false then return nil,"snapshot_not_yet_available" end
    local fd=n.open(path,"r")
    if not fd then return nil,"snapshot_open_failed" end
    local opened=fd:stat()
    if not file_ok(opened) or not same(state,opened) or
       not same(dir,fs.lstat(directory)) then
        close(fd)
        return nil,"snapshot_inode_changed"
    end
    local payload,code=fd:readall(MAX_BYTES+1)
    local final_stat=fs.lstat(path)
    local stable=close(fd)
    if not stable or type(payload)~="string" or
       #payload~=opened.size or not file_ok(final_stat) or
       not same(state,final_stat) or
       not same(dir,fs.lstat(directory)) then
        return nil,"snapshot_readback_unverified"
    end
    local parsed,reason=decode(mods.json,payload)
    if not parsed then return nil,reason end
    return payload,{
        status="offline_bounded_snapshot_read",
        source_only_not_live=true,
        authentic_admin_session_not_established=true,
        snapshot_age_unverified=true,
        hardware_qualified=false,
        actual_isp_uptime_unverified=true,
        no_firmware_write=true,
    }
end

function M.publish(handle,directory,mode)
    if not permitted(directory,mode) then
        return nil,"snapshot_write_not_authorized"
    end
    if not owner(handle) then return nil,"exclusive_collector_owner_required" end
    local mods,why=load_fs()
    if not mods then return nil,why end
    local n,fs=mods.n,mods.fs
    local dir=trusted_dir(fs,directory)
    if not dir then return nil,"unsafe_snapshot_directory" end
    local body,reason=guarded.export_json(handle,"hour",100)
    if not body then return nil,reason or "collector_history_unavailable" end
    local checked,invalid=decode(mods.json,body)
    if not checked then return nil,invalid end
    local final=directory.."/"..FINAL_NAME
    local stage=directory.."/"..STAGE_NAME
    if fs.lstat(stage) then return nil,"stale_snapshot_stage_blocks_publish" end
    local previous,reason=existing_ok(fs,final)
    if previous==nil then return nil,reason end
    local fd=n.open(stage,n.open_flags("rdwr","creat","excl"),600)
    if not fd then return nil,"snapshot_stage_create_failed" end
    local opened=fd:stat()
    local after=fs.lstat(stage)
    if not file_ok(opened) or not file_ok(after) or
       not same(opened,after) or not same(dir,fs.lstat(directory)) then
        close(fd)
        return nil,"snapshot_stage_identity_changed"
    end
    local ok,wrote=pcall(function() return fd:writeall(body) end)
    if not ok or wrote~=#body then
        close(fd)
        return nil,"snapshot_stage_write_failed"
    end
    local synched,done=pcall(function() return fd:sync() end)
    if not synched or done~=true then
        close(fd)
        return nil,"snapshot_stage_sync_failed"
    end
    if not close(fd) then return nil,"snapshot_stage_close_failed" end
    local staged=fs.lstat(stage)
    if not file_ok(staged) or not same(opened,staged) or
       not same(dir,fs.lstat(directory)) then
        return nil,"snapshot_stage_changed"
    end
    if previous~=false then
        local now=fs.lstat(final)
        if not file_ok(now) or not same(previous,now) then
            return nil,"snapshot_target_changed"
        end
    elseif fs.lstat(final) then
        return nil,"snapshot_target_appeared"
    end
    if not fs.rename(stage,final) then
        return nil,"snapshot_atomic_rename_failed"
    end
    local loaded,read_error=M.read(directory,mode)
    if loaded~=body then
        return nil,"snapshot_publish_readback_unverified"
    end
    return {
        status="offline_atomic_snapshot_verified",
        bytes=#body,maximum_bytes=MAX_BYTES,
        source_only_not_live=true,
        no_onu_flash_write=true,
        on_device_tmpfs_qualified=false,
        no_device_or_isp_contact=true,
        absolute_freshness_unknown=true,
        authenticated_http_access_not_yet_deployed=true,
        filesystem_atomicity_tested_offline_only=true,
    }
end

-- Stale stage recovery requires the owner lock, an exact private filename
-- and a verified regular root-owned inode. Never deletes the current view.
function M.discard_stale_stage(handle,directory,mode)
    if not permitted(directory,mode) then return nil,"stage_cleanup_not_authorized" end
    if not owner(handle) then return nil,"exclusive_collector_owner_required" end
    local mods,why=load_fs()
    if not mods then return nil,why end
    local fs=mods.fs
    local dir=trusted_dir(fs,directory)
    if not dir then return nil,"unsafe_snapshot_directory" end
    local name=directory.."/"..STAGE_NAME
    local candidate=fs.lstat(name)
    if not candidate then return {status="no_stale_stage"} end
    if not file_ok(candidate) then return nil,"unsafe_stale_stage" end
    if not same(candidate,fs.lstat(name)) or
       not same(dir,fs.lstat(directory)) then
        return nil,"stale_stage_inode_changed"
    end
    if not fs.unlink(name) then return nil,"stale_stage_unlink_failed" end
    return {
        status="verified_stale_stage_discarded",
        source_only_not_live=true,no_current_snapshot_deleted=true,
    }
end
-- H-027: require an active H-022 owner both before and after the
-- bounded file read. A stopped, crashed or absent publisher cannot
-- provide a supposedly current history response from leftover bytes.
function M.read_guarded(directory,lock_directory,mode)
    if not permitted(directory,mode) then
        return nil,"guarded_snapshot_read_not_authorized"
    end
    local lock=require "8311.history_process_lock"
    -- Two independent lock admissions. The long-lived collector lock
    -- does not grant a newly started writer permission to serve a
    -- previous session's cache. publication.lock is acquired only
    -- after this writer publishes and verifies its OWN first snapshot.
    local gate=require "8311.history_publication_gate"
    local held,reason=lock.writer_present(lock_directory)
    if held~=true then
        return nil,reason or "no_guarded_history_writer"
    end
    local admitted,gate_reason=gate.reader_admitted(lock_directory,mode)
    if admitted~=true then
        return nil,gate_reason or "no_verified_snapshot_publisher"
    end
    local body,info=M.read(directory,mode)
    if not body then return nil,info end
    local afterward,gate_why=gate.reader_admitted(lock_directory,mode)
    if afterward~=true then
        return nil,gate_why or "publisher_lost_during_read"
    end
    local after,why=lock.writer_present(lock_directory)
    if after~=true then
        return nil,why or "guarded_writer_lost_during_read"
    end
    info.guard_owner_checked_before_and_after=true
    info.publication_gate_checked_before_and_after=true
    info.producer_runtime_freshness_not_qualified=true
    return body,info
end

-- Controlled stop and fresh-session admission revoke the source-only
-- cached view while the guarded owner still holds the kernel lock.
-- Crashes may leave bytes on disk, but read_guarded refuses them.
function M.invalidate(handle,directory,mode)
    if not permitted(directory,mode) then
        return nil,"snapshot_invalidation_not_authorized"
    end
    if not owner(handle) then return nil,"exclusive_collector_owner_required" end
    local mods,why=load_fs()
    if not mods then return nil,why end
    local fs=mods.fs
    local dir=trusted_dir(fs,directory)
    if not dir then return nil,"unsafe_snapshot_directory" end
    local target=directory.."/"..FINAL_NAME
    local previous,reason=existing_ok(fs,target)
    if previous==nil then return nil,reason end
    if previous==false then
        return {status="no_snapshot_to_invalidate",
            source_only_not_live=true}
    end
    if not same(previous,fs.lstat(target)) or
       not same(dir,fs.lstat(directory)) then
        return nil,"snapshot_invalidation_inode_changed"
    end
    if not fs.unlink(target) then return nil,"snapshot_invalidation_failed" end
    if fs.lstat(target) then return nil,"snapshot_invalidation_unverified" end
    return {status="guarded_snapshot_invalidated",
        source_only_not_live=true,no_firmware_image_changed=true}
end

return M
