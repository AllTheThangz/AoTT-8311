-- H-022 guarded single-owner H-021 source collector, offline only.
-- Fails closed on lock contention or unsafe directory. No daemon/HTTP/flash.
local lock=require "8311.history_process_lock"
local collector=require "8311.history_collector"
local M={}
local OWNED=setmetatable({}, {__mode="k"})

local function session(handle)
    if type(handle)~="table" or
       handle.source_only_not_deployed~=true then return nil end
    local record=OWNED[handle]
    if not record or not lock.status(record.lock) then return nil end
    return record
end

-- A real device entrypoint is not available. This composition is
-- intentionally limited to the H-021 offline_synthetic mode.
-- The lock file is held throughout all collector operations.
function M.new(directory,preferences,capability,mode)
    if mode~="offline_synthetic" then
        return nil,"hardware_admission_not_qualified"
    end
    local owner,reason=lock.acquire(directory)
    if not owner then return nil,reason end
    local instance,why=collector.new_independent(
        preferences,capability,mode)
    if not instance then
        local released=lock.release(owner)
        if not released then return nil,"source_lock_release_unverified" end
        return nil,why
    end
    local handle={schema=1,source_only_not_deployed=true}
    OWNED[handle]={lock=owner,collector=instance}
    return handle,{
        status="offline_guarded_collector_ready",
        exclusive_kernel_owner=true,
        source_only_not_deployed=true,
        no_daemon_or_http_endpoint=true,
        no_flash_or_firmware_action=true,
        no_live_device_or_isp_claim=true,
    }
end

function M.tick(handle,now,provider)
    local state=session(handle)
    if not state then return nil,"guarded_collector_not_owned" end
    return collector.tick(state.collector,now,provider)
end

function M.status(handle)
    local state=session(handle)
    if not state then return nil,"guarded_collector_not_owned" end
    local result=collector.status(state.collector)
    if not result then return nil,"guarded_collector_unavailable" end
    result.source_only_not_deployed=true
    result.exclusive_kernel_owner=true
    result.cross_process_advisory_lock=true
    return result
end

function M.view(handle,range,limit)
    local state=session(handle)
    if not state then return nil,"guarded_collector_not_owned" end
    return collector.view(state.collector,range,limit)
end

function M.export_json(handle,range,limit)
    local state=session(handle)
    if not state then return nil,"guarded_collector_not_owned" end
    return collector.export_json(state.collector,range,limit)
end

function M.export_csv(handle,range,limit)
    local state=session(handle)
    if not state then return nil,"guarded_collector_not_owned" end
    return collector.export_csv(state.collector,range,limit)
end

function M.close(handle)
    local state=session(handle)
    if not state then return nil,"guarded_collector_not_owned" end
    local stopped,why=collector.close(state.collector)
    if not stopped then return nil,why end
    local released,err=lock.release(state.lock)
    if not released then return nil,err end
    OWNED[handle]=nil
    return {
        status="offline_guarded_collector_closed",
        source_only_not_deployed=true,
        lock_file_is_never_unlinked=true,
        no_live_device_operation=true,
    }
end

return M
