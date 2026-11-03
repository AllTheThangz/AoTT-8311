-- H-020: source-only, single-owner H-011/H-014 readback collector.
-- An explicit caller invokes tick(). No timer, daemon, route, disk or boot hook.
-- Runtime activation is impossible without the offline_synthetic gate.
local sampler = require "8311.history_sampler"
local probe = require "8311.history_native_probe"
local exporter = require "8311.history_export"
local M={}
local PRIV=setmetatable({}, {__mode="k"})
-- Process-local singleton only; actual deployments still require an
-- independently qualified cross-process lock and supervisor.
local ACTIVE=setmetatable({}, {__mode="v"})
local RETRY_SECONDS={15,30,60,120,300}
local MAX_MONOTONIC=1e12

local function integer(v,lo,hi)
    return type(v)=="number" and v==v and v~=math.huge and
           v~=-math.huge and v==math.floor(v) and v>=lo and v<=hi
end
local function seconds(v)
    return type(v)=="number" and v==v and v~=math.huge and
           v~=-math.huge and v>=0 and v<=MAX_MONOTONIC
end
local function private(handle)
    if type(handle)~="table" or handle.schema~=1 or
       handle.source_only_not_live~=true then
        return nil
    end
    return PRIV[handle]
end
local function select_preferences(p,independent)
    if type(p)~="table" or p.schema~=1 or
       not integer(p.revision,1,9007199254740990) or
       p.source_only_not_live~=true or p.no_device_write~=true or
       type(p.values)~="table" then
        return nil,"invalid_source_preferences"
    end
    local v=p.values
    for _,key in ipairs({
        "sampling_enabled","persist_enabled","local_alerts_enabled",
        "remote_notifications",
    }) do
        if type(v[key])~="boolean" then
            return nil,"invalid_source_preferences"
        end
    end
    if not integer(v.pon_interval_seconds,30,300) or
       not integer(v.host_interval_seconds,30,300) or
       not integer(v.ram_sample_limit,30,720) or
       not integer(v.ram_event_limit,16,256) or
       not integer(v.heavy_probe_seconds,0,900) then
        return nil,"invalid_source_preferences"
    end
    if v.persist_enabled or v.local_alerts_enabled or
       v.remote_notifications or v.heavy_probe_seconds~=0 or
       v.rx_low_dbm~=nil or v.retention_days~=0 then
        return nil,"unimplemented_collector_output_requested"
    end
    if independent and v.optical_interval_seconds~=120 then
        -- Optical counters are not wired into this native adapter.
        -- Never accept a changed optical cadence without executing it.
        return nil,"optical_cadence_not_implemented"
    end
    local pon,host=v.pon_interval_seconds,v.host_interval_seconds
    if not independent and pon~=host then
        return nil,"independent_channel_cadences_not_yet_implemented"
    end
    if independent then
        local choices={ [30]=true,[60]=true,[120]=true,[300]=true }
        if not choices[pon] or not choices[host] or
           (3600/pon)*3+(3600/host)*4>720 then
            return nil,"collector_interval_not_qualified"
        end
    elseif pon~=60 and pon~=120 and pon~=300 then
        return nil,"collector_interval_not_qualified"
    end
    return {
        enabled=v.sampling_enabled,
        interval=pon==host and pon or nil,
        pon_interval=pon,host_interval=host,
        samples=v.ram_sample_limit,
        events=v.ram_event_limit,
        version=p.revision,
    }
end

function M.new(preferences,capability,mode)
    local selected,reason=select_preferences(preferences)
    if not selected then return nil,reason end
    if type(capability)~="table" or
       capability.kind~="source_only" or
       (capability.native_qualified~=true and
        capability.native_qualified~=false) then
        return nil,"invalid_source_capability"
    end
    if selected.enabled and (capability.native_qualified~=true or
       mode~="offline_synthetic") then
        return nil,"hardware_not_directly_qualified"
    end
    if selected.enabled and ACTIVE.handle then
        return nil,"collector_owner_exists"
    end
    local history,why=sampler.new({
        max_samples=selected.samples,max_events=selected.events,
    })
    if not history then return nil,why end
    local token={schema=1,source_only_not_live=true}
    PRIV[token]={
        history=history,enabled=selected.enabled,
        interval=selected.interval,prefs_revision=selected.version,
        pon_interval=selected.pon_interval,
        host_interval=selected.host_interval,mode="combined",
        last_tick=nil,next_due=nil,
        in_flight=false,failures=0,failed_attempts=0,
        attempts=0,samples=0,last_error=nil,last_availability=nil,
    }
    if selected.enabled then ACTIVE.handle=token end
    return token
end

-- Releasing an offline handle neither terminates a device process nor
-- erases any persisted history. There are no spawned tasks in this model.
function M.close(handle)
    local p=private(handle)
    if not p then return nil,"invalid_collector_handle" end
    if p.in_flight then return nil,"native_probe_already_in_flight" end
    PRIV[handle]=nil
    if ACTIVE.handle==handle then ACTIVE.handle=nil end
    return {status="closed",source_only_not_live=true,
            no_device_write=true,no_background_task=true}
end

local function receipt(p)
    return {
        schema=1,enabled=p.enabled,
        status=p.enabled and "offline_synthetic_only" or "disabled",
        source_only_not_live=true,
        hardware_qualified=false,
        no_timer_or_background_process=true,
        no_device_write=true,no_flash_write=true,
        no_network_or_alert_delivery=true,
        no_live_firmware_integration=true,
        one_shared_native_sample_interval_seconds=p.interval,
        pon_interval_seconds=p.pon_interval,
        host_interval_seconds=p.host_interval,
        pon_next_due_uptime=p.next_pon_due,
        host_next_due_uptime=p.next_host_due,
        independent_channel_cadences_implemented=p.mode=="independent",
        next_due_uptime=p.next_due,
        calls=p.attempts,samples_accepted=p.samples,
        failed_attempts=p.failed_attempts,
        consecutive_failures=p.failures,
        last_error=p.last_error,
        retained_samples=p.history.samples_count,
        retained_events=p.history.events_count,
    }
end

function M.status(handle)
    local p=private(handle)
    if not p then return nil,"invalid_collector_handle" end
    return receipt(p)
end

local function retry(p,now,reason)
    p.failed_attempts=p.failed_attempts+1
    p.failures=math.min(p.failures+1,#RETRY_SECONDS)
    p.last_error=reason
    p.next_due=now+RETRY_SECONDS[p.failures]
    return {
        schema=1,status="retry_scheduled",
        retry_after_seconds=RETRY_SECONDS[p.failures],
        last_error=reason,no_device_write=true,
        no_reboot_or_flash_operation=true,
        source_only_not_live=true,
    }
end

-- A qualified, later scheduler must provide a monotonic tick and exactly
-- one owner. This model has NO scheduler and cannot activate on an ONU.
function M.tick(handle,now,provider)
    local p=private(handle)
    if p and p.mode=="independent" then
        return M.tick_independent(handle,now,provider)
    end
    if not p then return nil,"invalid_collector_handle" end
    if not seconds(now) then return nil,"invalid_tick_clock" end
    if not p.enabled then
        return {
            status="disabled",no_native_probe=true,
            source_only_not_live=true,
        }
    end
    if p.in_flight then return nil,"native_probe_already_in_flight" end
    if p.last_tick and now<p.last_tick then
        return nil,"collector_clock_regressed"
    end
    if p.next_due and now<p.next_due then
        return {
            status="not_due",next_due_uptime=p.next_due,
            no_native_probe=true,source_only_not_live=true,
        }
    end
    if type(provider)~="table" or
       type(provider.read)~="function" or
       type(provider.run)~="function" then
        return nil,"invalid_readonly_provider"
    end
    p.in_flight=true
    p.last_tick=now
    p.attempts=p.attempts+1
    -- The actual source reader enforces boot+uptime twice, native argv
    -- allowlists, output caps, and an <=12s read window independently.
    local ok,snapshot,availability=pcall(probe.read_once,provider)
    if not ok or not snapshot then
        p.in_flight=false
        local why=ok and availability or "native_reader_exception"
        return retry(p,now,why)
    end
    if not seconds(snapshot.uptime) or
       math.abs(snapshot.uptime-now)>12 then
        p.in_flight=false
        return retry(p,now,"snapshot_clock_mismatch")
    end
    -- All unavailable measurements are a failed observation, not proof
    -- that the fiber went down, or a zero traffic interval.
    if availability.pon=="unavailable" and
       availability.host_link=="unavailable" and
       availability.host_counters=="unavailable" then
        p.in_flight=false
        return retry(p,now,"no_valid_native_measurement")
    end
    local valid,event_or_error=pcall(sampler.ingest,p.history,snapshot)
    p.in_flight=false
    if not valid or not event_or_error then
        return retry(p,now,valid and "history_sample_rejected"
                                      or "history_ingest_exception")
    end
    p.samples=p.samples+1
    p.failures=0
    p.last_error=nil
    p.next_due=now+p.interval
    p.last_availability={
        pon=availability.pon,
        host_link=availability.host_link,
        host_counters=availability.host_counters,
    }
    return {
        schema=1,status="sample_accepted",
        next_due_uptime=p.next_due,
        history_status=event_or_error.status,
        has_rate=event_or_error.has_rate,
        events_added=event_or_error.events_added,
        samples_retained=event_or_error.samples_retained,
        events_retained=event_or_error.events_retained,
        availability=p.last_availability,
        source_only_not_live=true,
        no_device_write=true,no_flash_write=true,
        no_isp_availability_proof=true,
    }
end

-- Independent PON and host cadence source constructor. No actual
-- hardware qualification or service activation is performed.
function M.new_independent(preferences,capability,mode)
    local selected,why=select_preferences(preferences,true)
    if not selected then return nil,why end
    if type(capability)~="table" or
       capability.kind~="source_only" or
       type(capability.native_qualified)~="boolean" then
        return nil,"invalid_source_capability"
    end
    if selected.enabled and (capability.native_qualified~=true or
       mode~="offline_synthetic") then
        return nil,"hardware_not_directly_qualified"
    end
    if selected.enabled and ACTIVE.handle then
        return nil,"collector_owner_exists"
    end
    local history,reason=sampler.new({
        max_samples=selected.samples,max_events=selected.events,
    })
    if not history then return nil,reason end
    local handle={schema=1,source_only_not_live=true}
    PRIV[handle]={
        history=history,enabled=selected.enabled,
        pon_interval=selected.pon_interval,
        host_interval=selected.host_interval,
        interval=selected.interval,mode="independent",
        prefs_revision=selected.version,last_tick=nil,last_boot=nil,
        next_due=nil,next_pon_due=nil,next_host_due=nil,
        in_flight=false,failures=0,failed_attempts=0,
        attempts=0,samples=0,last_error=nil,last_availability=nil,
    }
    if selected.enabled then ACTIVE.handle=handle end
    return handle
end

-- H-021 independent selective sampling. Only due channels are read;
-- never replay or zero-fill an unobserved channel. No internal scheduler.
function M.tick_independent(handle,now,provider)
    local p=private(handle)
    if not p or p.mode~="independent" then
        return nil,"invalid_independent_collector"
    end
    if not seconds(now) then return nil,"invalid_tick_clock" end
    if not p.enabled then
        return {status="disabled",no_native_probe=true,
                source_only_not_live=true}
    end
    if p.in_flight then return nil,"native_probe_already_in_flight" end
    local regressed=p.last_tick and now<p.last_tick
    -- A decreasing uptime is allowed only if the bounded native reader
    -- independently proves a *different* boot identifier. No stale
    -- counter pair may cross that boot boundary.
    if p.next_due and now<p.next_due and not regressed then
        return {status="not_due",next_due_uptime=p.next_due,
                no_native_probe=true,source_only_not_live=true}
    end
    local pon_due=regressed or p.next_pon_due==nil or now>=p.next_pon_due
    local host_due=regressed or p.next_host_due==nil or now>=p.next_host_due
    if not pon_due and not host_due then
        return {status="not_due",next_due_uptime=p.next_due,
                no_native_probe=true,source_only_not_live=true}
    end
    if type(provider)~="table" or
       type(provider.read)~="function" or
       type(provider.run)~="function" then
        return nil,"invalid_readonly_provider"
    end
    p.in_flight=true
    local prior_tick=p.last_tick
    p.last_tick=now
    p.attempts=p.attempts+1
    local selection={pon=pon_due,host=host_due}
    local ok,snapshot,availability=pcall(probe.read_selected,provider,selection)
    if not ok or not snapshot then
        p.in_flight=false
        if regressed then
            p.last_tick=prior_tick
            return nil,"reboot_identity_unverified"
        end
        return retry(p,now,ok and availability or
                     "native_reader_exception")
    end
    if regressed and (not p.last_boot or
       snapshot.boot==p.last_boot) then
        p.in_flight=false
        p.last_tick=prior_tick
        return nil,"collector_clock_regressed"
    end
    if not seconds(snapshot.uptime) or
       math.abs(snapshot.uptime-now)>12 then
        p.in_flight=false
        if regressed then p.last_tick=prior_tick end
        return nil,"snapshot_clock_mismatch"
    end
    local valid_pon=pon_due and availability.pon=="observed"
    local valid_host=host_due and
       (availability.host_link=="observed" or
        availability.host_counters=="observed")
    if not valid_pon and not valid_host then
        p.in_flight=false
        if regressed then
            p.last_tick=prior_tick
            return nil,"reboot_observation_unavailable"
        end
        return retry(p,now,"no_valid_native_measurement")
    end
    local accepted,sample=pcall(sampler.ingest_selected,p.history,snapshot)
    p.in_flight=false
    if not accepted or not sample then
        if regressed then
            p.last_tick=prior_tick
            return nil,"reboot_sample_unverified"
        end
        return retry(p,now,accepted and "selected_history_sample_rejected"
                                  or "selected_history_ingest_exception")
    end
    p.last_boot=snapshot.boot
    p.samples=p.samples+1
    p.failures=0
    p.last_error=nil
    if pon_due then p.next_pon_due=now+p.pon_interval end
    if host_due then p.next_host_due=now+p.host_interval end
    p.next_due=math.min(p.next_pon_due,p.next_host_due)
    p.last_availability={
        pon=availability.pon,host_link=availability.host_link,
        host_counters=availability.host_counters,
    }
    return {
        schema=1,status="sample_accepted",
        due_pon=pon_due,due_host=host_due,
        next_due_uptime=p.next_due,
        pon_next_due_uptime=p.next_pon_due,
        host_next_due_uptime=p.next_host_due,
        history_status=sample.status,has_rate=sample.has_rate,
        events_added=sample.events_added,
        samples_retained=sample.samples_retained,
        events_retained=sample.events_retained,
        availability=p.last_availability,
        source_only_not_live=true,no_device_write=true,
        no_flash_write=true,no_isp_availability_proof=true,
    }
end

function M.view(handle,range,limit)
    local p=private(handle)
    if not p then return nil,"invalid_collector_handle" end
    return exporter.project(p.history,range,limit)
end

function M.export_json(handle,range,limit)
    local p=private(handle)
    if not p then return nil,"invalid_collector_handle" end
    return exporter.export_json(p.history,range,limit)
end

function M.export_csv(handle,range,limit)
    local p=private(handle)
    if not p then return nil,"invalid_collector_handle" end
    return exporter.export_csv(p.history,range,limit)
end

return M
