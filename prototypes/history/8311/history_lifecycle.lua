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
        snapshot_source_enabled=p.snapshot_directory~=nil,
        verified_snapshot_reader_admitted=p.publication_handle~=nil,
        snapshots_published=p.snapshots_published,
        snapshot_publish_failures=p.snapshot_publish_failures,
        snapshot_last_source_uptime=p.snapshot_last_clock,
        snapshot_provenance="offline_synthetic_unattested",
        live_history_endpoint_installed=false,
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
        snapshot_directory=nil,snapshot_last_clock=nil,
        publication_handle=nil,
        snapshots_published=0,snapshot_publish_failures=0,
    }
    return token,receipt(PRIVATE[token])
end

-- H-027 optional source-only snapshot configuration, frozen before
-- the first guarded collector admission. The approved directory is an
-- independently provisioned private offline test directory, never a
-- URI, firmware setting, arbitrary pathname or production target.
function M.configure_snapshot(token,directory,mode)
    local p=owner(token)
    if not p then return nil,"invalid_lifecycle_handle" end
    if mode~="offline_synthetic" or type(directory)~="string" or
       #directory>119 or not directory:match(
           "^/var/tmp/aott%-h026%-ipc%-test%-%w+$") then
        return nil,"unqualified_snapshot_directory"
    end
    if p.phase~="stopped" or p.lifetime_starts~=0 or
       p.snapshot_directory~=nil then
        return nil,"snapshot_configuration_frozen"
    end
    p.snapshot_directory=directory
    return {status="offline_snapshot_configured",
        source_only_not_deployed=true,no_production_activation=true,
        actual_device_storage_unqualified=true,
        no_collector_started=true}
end

local function invalidate_snapshot(p)
    if not p.snapshot_directory or not p.handle then return true end
    local bridge=require "8311.history_snapshot_ipc"
    local ok,result=pcall(bridge.invalidate,p.handle,
        p.snapshot_directory,"offline_synthetic")
    return ok and type(result)=="table"
end

-- Publication admission ends BEFORE invalidation or collector lock
-- release. If it cannot be verified, freeze rather than advertising
-- a healthy reader. The separate reader also requires the main lock.
local function revoke_admission(p)
    if not p.publication_handle then return true end
    local gate=require "8311.history_publication_gate"
    local ok,result=pcall(gate.revoke_writer,p.publication_handle)
    if not ok or type(result)~="table" then return false end
    p.publication_handle=nil
    return true
end

-- All backoff and restart decisions are made in a caller-provided
-- monotonic time domain. There is no automatic wakeup or sleep.
local function cooled(p,now,why)
    local revoked=revoke_admission(p)
    local invalidated=invalidate_snapshot(p)
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
    if not revoked or not invalidated then
        p.phase="unsafe"
        p.last_error=not revoked and
            "publication_gate_revocation_unverified" or
            "snapshot_invalidation_failed"
        p.next_start=nil
        return nil,p.last_error
    end
    p.snapshot_last_clock=nil
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
    -- After acquiring the main lock, revoke any previous cache before
    -- first publication. H-028's separate publication gate remains
    -- unheld during this gap so a reader cannot accept old JSON.
    if p.snapshot_directory then
        local ipc=require "8311.history_snapshot_ipc"
        local verified,removed=pcall(ipc.invalidate,handle,
            p.snapshot_directory,"offline_synthetic")
        if not verified or not removed then
            pcall(guarded.close,handle)
            p.phase="unsafe"
            p.last_error="snapshot_start_invalidation_unverified"
            return nil,"snapshot_start_invalidation_unverified"
        end
        -- A previous process can die after writing its temporary file.
        -- Only a verified regular single-link stage may be discarded,
        -- while this process still holds the exclusive H-022 lock.
        local cleaned,discarded=pcall(ipc.discard_stale_stage,handle,
            p.snapshot_directory,"offline_synthetic")
        if not cleaned or not discarded then
            pcall(guarded.close,handle)
            p.phase="unsafe"
            p.last_error="snapshot_stale_stage_unverified"
            return nil,"snapshot_stale_stage_unverified"
        end
    end
    p.phase="running"
    p.handle=handle
    p.publication_handle=nil
    p.snapshot_last_clock=nil
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
    local publication="not_configured"
    if p.snapshot_directory then
        -- A verified boot-epoch transition must not serve a snapshot
        -- from the previous boot while the new one is publishing.
        if value.history_status=="reboot" and
           not revoke_admission(p) then
            p.snapshot_publish_failures=p.snapshot_publish_failures+1
            return cooled(p,now,"publication_gate_revocation_failed")
        end
        local last=p.snapshot_last_clock
        if last==nil or value.history_status=="reboot" or
           (now>=last and now-last>=60) then
            local bridge=require "8311.history_snapshot_ipc"
            local published,record=pcall(bridge.publish,p.handle,
                p.snapshot_directory,"offline_synthetic")
            if not published or type(record)~="table" then
                p.snapshot_publish_failures=p.snapshot_publish_failures+1
                return cooled(p,now,"snapshot_publish_failed")
            end
            -- H-028: the second kernel lock is acquired ONLY AFTER
            -- the new canonical snapshot has passed readback. A new
            -- main collector lock never admits predecessor bytes.
            if not p.publication_handle then
                local gate=require "8311.history_publication_gate"
                local admitted,token=pcall(gate.admit_writer,p.directory,
                                           "offline_synthetic")
                if not admitted or type(token)~="table" then
                    p.snapshot_publish_failures=p.snapshot_publish_failures+1
                    return cooled(p,now,"publication_gate_admission_failed")
                end
                p.publication_handle=token
            end
            p.snapshot_last_clock=now
            p.snapshots_published=p.snapshots_published+1
            publication="verified_offline_snapshot"
        else
            publication="not_due"
        end
    end
    local out=receipt(p,"sample_accepted")
    out.snapshot_publish_status=publication
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
        local revoked=revoke_admission(p)
        local invalidated=invalidate_snapshot(p)
        local ok,closed=pcall(guarded.close,p.handle)
        if not ok or not closed then
            p.phase="unsafe"
            p.last_error="guarded_close_unverified"
            return nil,"guarded_close_unverified"
        end
        if not revoked or not invalidated then
            p.phase="unsafe"
            p.last_error=not revoked and
                "publication_gate_revocation_unverified" or
                "snapshot_invalidation_failed"
            return nil,p.last_error
        end
    end
    p.handle=nil
    p.publication_handle=nil
    p.snapshot_last_clock=nil
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
