-- AoTT-8311 H-023 source-only supervised collector lifecycle.
-- Manual step API. No cron, procd, background process or device writes.
-- Actual kernel lock and H-021 collector are supplied by H-022 guarded source.
local guarded=require "8311.history_guarded_collector"
local M={}
local PRIVATE=setmetatable({}, {__mode="k"})
local START_BACKOFF={60,120,300,900}
local FAILURE_THRESHOLD=4
local MAX_RESTARTS=3
local MAX_MONOTONIC=1e12

local function number(v)
    return type(v)=="number" and v==v and v~=math.huge and
           v~=-math.huge and v>=0 and v<=MAX_MONOTONIC
end
-- Copy accepted scalar configuration before the guarded start, so a
-- caller cannot mutate an already-reviewed policy while a session waits.
local function clone_preferences(raw)
    local result={schema=raw.schema,revision=raw.revision,
        source_only_not_live=raw.source_only_not_live,
        no_device_write=raw.no_device_write,values={}}
    for key,value in pairs(raw.values) do
        if type(key)~="string" or
           (type(value)~="number" and type(value)~="string" and
            type(value)~="boolean") then
            return nil,"invalid_preference_value"
        end
        result.values[key]=value
    end
    return result
end

local function owner(token)
    if type(token)~="table" or token.source_only_not_deployed~=true or
       token.schema~=1 then return nil end
    return PRIVATE[token]
end
local function receipt(p,code)
    return {
        schema=1,
        status=code or p.phase,
        phase=p.phase,
        source_only_not_deployed=true,
        no_background_service=true,
        no_device_write=true,
        no_alert_or_network_delivery=true,
        no_flash_write=true,
        no_production_activation=true,
        hardware_runtime_unqualified=true,
        running=p.phase=="running",
        owns_kernel_lock=p.phase=="running",
        lifetime_starts=p.lifetime_starts,
        lifetime_samples=p.lifetime_samples,
        lifetime_failed_samples=p.lifetime_failed_samples,
        restart_count=p.restart_count,
        failed_start_count=p.failed_start_count,
        consecutive_reader_failures=p.reader_failures,
        next_start_uptime=p.next_start,
        next_collector_uptime=p.next_due,
        last_error=p.last_error,
        circuit_open=p.phase=="circuit_open",
    }
end

-- Explicit synthetic-only admission. An installed procd script or
-- authenticated runtime configuration is NOT provided by this module.
function M.new(directory,preferences,capability,mode)
    if mode~="offline_synthetic" then
        return nil,"hardware_lifecycle_not_qualified"
    end
    if type(directory)~="string" or
       type(preferences)~="table" or preferences.schema~=1 or
       type(preferences.values)~="table" or
       preferences.source_only_not_live~=true or
       preferences.no_device_write~=true or
       type(capability)~="table" or
       capability.kind~="source_only" or
       capability.native_qualified~=true then
        return nil,"invalid_source_lifecycle"
    end
    if preferences.values.sampling_enabled~=true or
       preferences.values.persist_enabled~=false or
       preferences.values.local_alerts_enabled~=false or
       preferences.values.remote_notifications~=false then
        return nil,"unavailable_lifecycle_feature"
    end
    local snapshot,reason=clone_preferences(preferences)
    if not snapshot then return nil,reason end
    local token={schema=1,source_only_not_deployed=true}
    PRIVATE[token]={
        directory=directory,
        preferences=snapshot,
        capability={kind="source_only",native_qualified=true},
        phase="stopped",handle=nil,
        last_start_clock=nil,next_start=nil,
        next_due=nil,last_error=nil,
        last_action_clock=nil,
        failed_start_count=0,reader_failures=0,
        lifetime_starts=0,lifetime_samples=0,
        lifetime_failed_samples=0,restart_count=0,
    }
    return token,receipt(PRIVATE[token])
end

-- All backoff and restart decisions are made in a caller-provided
-- monotonic time domain. There is no automatic wakeup or sleep.
local function cooled(p,now,why)
    if p.handle then
        local ok,closed=pcall(guarded.close,p.handle)
        if not ok or not closed then
            p.phase="unsafe"
            p.last_error="guarded_close_unverified"
            p.next_start=nil
            return nil,"guarded_close_unverified"
        end
        p.handle=nil
    end
    p.next_due=nil
    p.reader_failures=0
    p.restart_count=p.restart_count+1
    p.last_error=why
    if p.restart_count>MAX_RESTARTS then
        p.phase="circuit_open"
        p.next_start=nil
        return receipt(p,"circuit_open")
    end
    p.phase="cooldown"
    p.next_start=now+START_BACKOFF[p.restart_count]
    return receipt(p,"cooldown")
end

function M.start(token,now)
    local p=owner(token)
    if not p then return nil,"invalid_lifecycle_handle" end
    if not number(now) then return nil,"invalid_lifecycle_clock" end
    if p.phase=="closed" or p.phase=="unsafe" or
       p.phase=="circuit_open" then
        return nil,"lifecycle_not_restartable"
    end
    if p.phase=="running" then
        return receipt(p,"already_running")
    end
    if p.last_action_clock and now<p.last_action_clock then
        return nil,"lifecycle_clock_regressed"
    end
    if p.next_start and now<p.next_start then
        return receipt(p,"cooldown_not_elapsed")
    end
    local ok,handle,why=pcall(guarded.new,p.directory,
        p.preferences,p.capability,"offline_synthetic")
    p.last_action_clock=now
    if not ok or not handle then
        local cause=ok and why or "guarded_start_exception"
        -- Unsafe directory and invalid preferences never retry. Only
        -- external lock contention may be retried after bounded delay.
        if cause=="collector_held_by_other_process" or
           cause=="collector_already_owned_in_process" or
           cause=="lock_file_create_conflict" then
            p.failed_start_count=p.failed_start_count+1
            p.last_error="collector_owner_busy"
            if p.failed_start_count>MAX_RESTARTS then
                p.phase="circuit_open"
                p.next_start=nil
                return receipt(p,"circuit_open")
            end
            p.phase="cooldown"
            p.next_start=now+START_BACKOFF[p.failed_start_count]
            return receipt(p,"owner_busy")
        end
        p.phase="unsafe"
        p.last_error="unsafe_start_rejected"
        p.next_start=nil
        return nil,cause
    end
    p.phase="running"
    p.handle=handle
    p.lifetime_starts=p.lifetime_starts+1
    p.reader_failures=0
    p.failed_start_count=0
    p.last_error=nil
    p.next_start=nil
    p.last_start_clock=now
    p.next_due=now
    return receipt(p,"running")
end

function M.step(token,now,provider)
    local p=owner(token)
    if not p then return nil,"invalid_lifecycle_handle" end
    if not number(now) then return nil,"invalid_lifecycle_clock" end
    if p.phase=="stopped" then
        return receipt(p,"stopped_no_auto_start")
    elseif p.phase=="cooldown" then
        return receipt(p,now>=p.next_start and
            "restart_permitted_manual_start" or "cooldown_not_elapsed")
    elseif p.phase~="running" then
        return receipt(p)
    end
    -- Only the underlying H-021 native reader may validate a real
    -- reboot with a lower monotonic uptime and changed kernel boot ID.
    local ok,value,reason=pcall(guarded.tick,p.handle,now,provider)
    if not ok then
        p.lifetime_failed_samples=p.lifetime_failed_samples+1
        return cooled(p,now,"guarded_tick_exception")
    end
    if not value then
        if reason=="collector_clock_regressed" or
           reason=="reboot_identity_unverified" or
           reason=="snapshot_clock_mismatch" or
           reason=="invalid_tick_clock" then
            return nil,reason
        end
        p.lifetime_failed_samples=p.lifetime_failed_samples+1
        return cooled(p,now,"guarded_tick_rejected")
    end
    if value.status=="not_due" then
        p.next_due=value.next_due_uptime
        return receipt(p,"not_due")
    elseif value.status=="retry_scheduled" then
        p.reader_failures=p.reader_failures+1
        p.lifetime_failed_samples=p.lifetime_failed_samples+1
        p.next_due=now+value.retry_after_seconds
        p.last_error=value.last_error
        if p.reader_failures>=FAILURE_THRESHOLD then
            return cooled(p,now,"reader_failure_limit")
        end
        return receipt(p,"reader_backoff")
    elseif value.status~="sample_accepted" then
        return cooled(p,now,"unexpected_collector_status")
    end
    p.lifetime_samples=p.lifetime_samples+1
    p.reader_failures=0
    p.next_due=value.next_due_uptime
    p.last_error=nil
    local out=receipt(p,"sample_accepted")
    out.due_pon=value.due_pon
    out.due_host=value.due_host
    out.has_rate=value.has_rate
    out.history_status=value.history_status
    out.pon_observation=value.availability and value.availability.pon
    out.host_observation=value.availability and value.availability.host_link
    return out
end

function M.stop(token)
    local p=owner(token)
    if not p then return nil,"invalid_lifecycle_handle" end
    if p.phase=="closed" then return nil,"lifecycle_closed" end
    if p.phase=="unsafe" then return nil,"lifecycle_unsafe_close" end
    -- A tripped circuit breaker requires an entirely new, explicitly
    -- reviewed session. Ordinary stop/start cannot reset its budget.
    if p.phase=="circuit_open" then return receipt(p,"circuit_open") end
    if p.phase=="running" then
        local ok,closed=pcall(guarded.close,p.handle)
        if not ok or not closed then
            p.phase="unsafe"
            p.last_error="guarded_close_unverified"
            return nil,"guarded_close_unverified"
        end
    end
    p.handle=nil
    p.phase="stopped"
    p.next_start=nil
    p.next_due=nil
    p.reader_failures=0
    p.failed_start_count=0
    return receipt(p,"stopped")
end

function M.shutdown(token)
    local p=owner(token)
    if not p then return nil,"invalid_lifecycle_handle" end
    if p.phase=="closed" then return nil,"lifecycle_closed" end
    if p.phase=="unsafe" then return nil,"lifecycle_unsafe_close" end
    local result,why=M.stop(token)
    if not result then return nil,why end
    p.phase="closed"
    p.handle=nil
    p.next_start=nil
    p.next_due=nil
    return receipt(p,"closed")
end

function M.status(token)
    local p=owner(token)
    if not p then return nil,"invalid_lifecycle_handle" end
    if p.phase=="running" then
        local checked,locked=pcall(guarded.status,p.handle)
        if not checked or not locked then
            p.phase="unsafe"
            p.last_error="guarded_lock_lost"
            return nil,"guarded_lock_lost"
        end
    end
    return receipt(p)
end

function M.history(token,range,limit)
    local p=owner(token)
    if not p or p.phase~="running" then
        return nil,"collector_not_running"
    end
    return guarded.view(p.handle,range,limit)
end

function M.export_json(token,range,limit)
    local p=owner(token)
    if not p or p.phase~="running" then
        return nil,"collector_not_running"
    end
    return guarded.export_json(p.handle,range,limit)
end

return M
