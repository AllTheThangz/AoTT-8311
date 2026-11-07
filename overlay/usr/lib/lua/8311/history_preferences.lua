-- AoTT-8311 H-018 residential history preferences, source-only.
-- Pure Lua 5.1, no filesystem, network, scheduler, service or firmware writes.
local M={}
local KNOWN={
    sampling_enabled=true,pon_interval_seconds=true,
    host_interval_seconds=true,optical_interval_seconds=true,
    heavy_probe_seconds=true,ram_sample_limit=true,ram_event_limit=true,
    persist_enabled=true,retention_days=true,flush_interval_seconds=true,
    local_alerts_enabled=true,alert_pon_changes=true,
    alert_host_changes=true,alert_gaps=true,alert_reboots=true,
    rx_low_dbm=true,remote_notifications=true,
}
local INTERVAL={ [30]=true,[60]=true,[120]=true,[300]=true }
local OPTICAL={[60]=true,[120]=true,[300]=true}
local HEAVY={[0]=true,[300]=true,[900]=true}
local FLUSH={[900]=true,[1800]=true,[3600]=true,[7200]=true}
local DAYS={[0]=true,[7]=true,[30]=true,[90]=true}
local BOOLEANS={
    sampling_enabled=true,persist_enabled=true,
    local_alerts_enabled=true,alert_pon_changes=true,
    alert_host_changes=true,alert_gaps=true,alert_reboots=true,
    remote_notifications=true,
}
local DEFAULT={
    sampling_enabled=false,
    pon_interval_seconds=60,
    host_interval_seconds=60,
    optical_interval_seconds=120,
    heavy_probe_seconds=0,
    ram_sample_limit=120,
    ram_event_limit=128,
    persist_enabled=false,
    retention_days=0,
    flush_interval_seconds=1800,
    local_alerts_enabled=false,
    alert_pon_changes=true,
    alert_host_changes=true,
    alert_gaps=true,
    alert_reboots=true,
    remote_notifications=false,
}
local function integer(v,low,high)
    return type(v)=="number" and v==v and
           v~=math.huge and v~=-math.huge and
           v==math.floor(v) and v>=low and v<=high
end
local function finite(v,low,high)
    return type(v)=="number" and v==v and
           v~=math.huge and v~=-math.huge and v>=low and v<=high
end
local function copy(raw)
    local result={}
    for key in pairs(KNOWN) do
        if raw[key]~=nil then result[key]=raw[key] end
    end
    return result
end
local function default()
    return copy(DEFAULT)
end
function M.defaults()
    return {
        schema=1,revision=1,values=default(),
        source_only_not_live=true,no_device_write=true,
    }
end
local function caps(profile)
    -- These flags are injected ONLY by synthetic tests until actual
    -- board and runtime qualification. They are not authentication.
    if type(profile)~="table" or profile.kind~="source_only" then
        return nil,"invalid_source_profile"
    end
    for key in pairs(profile) do
        if key~="kind" and key~="native_qualified" and
           key~="optics_qualified" and key~="storage_qualified" and
           key~="alerts_qualified" and key~="rx_min_dbm" and
           key~="rx_max_dbm" then
            return nil,"unknown_capability"
        end
    end
    for _,name in ipairs({
        "native_qualified","optics_qualified",
        "storage_qualified","alerts_qualified",
    }) do
        if profile[name]~=nil and type(profile[name])~="boolean" then
            return nil,"invalid_capability"
        end
    end
    if profile.optics_qualified then
        if not finite(profile.rx_min_dbm,-40,0) or
           not finite(profile.rx_max_dbm,-40,0) or
           profile.rx_max_dbm-profile.rx_min_dbm<4 then
            return nil,"unsupported_optical_profile"
        end
    elseif profile.rx_min_dbm~=nil or profile.rx_max_dbm~=nil then
        return nil,"unqualified_optical_profile"
    end
    return profile
end
local function validate_field(key,value)
    if not KNOWN[key] then return nil,"unknown_history_setting" end
    if BOOLEANS[key] then
        if type(value)~="boolean" then return nil,"invalid_boolean" end
    elseif key=="pon_interval_seconds" or key=="host_interval_seconds" then
        if not INTERVAL[value] then return nil,"invalid_sample_interval" end
    elseif key=="optical_interval_seconds" then
        if not OPTICAL[value] then return nil,"invalid_optical_interval" end
    elseif key=="heavy_probe_seconds" then
        if not HEAVY[value] then return nil,"invalid_heavy_probe_interval" end
    elseif key=="ram_sample_limit" then
        if not integer(value,30,720) then return nil,"invalid_ram_sample_limit" end
    elseif key=="ram_event_limit" then
        if not integer(value,16,256) then return nil,"invalid_ram_event_limit" end
    elseif key=="retention_days" then
        if not DAYS[value] then return nil,"invalid_retention_days" end
    elseif key=="flush_interval_seconds" then
        if not FLUSH[value] then return nil,"invalid_flash_cadence" end
    elseif key=="rx_low_dbm" then
        -- Explicit false unsets an optional optical threshold. Lua nil
        -- cannot be carried as a key in an operator patch table.
        if value~=false and (not finite(value,-35,-5) or
           value*2~=math.floor(value*2)) then
            return nil,"invalid_rx_low_threshold"
        end
    end
    return true
end
local function validate_values(value,profile)
    if type(value)~="table" then return nil,"invalid_history_values" end
    for key in pairs(value) do
        if not KNOWN[key] then return nil,"unknown_history_setting" end
    end
    for key in pairs(KNOWN) do
        local v=value[key]
        if key~="rx_low_dbm" or v~=nil then
            if v==nil then return nil,"missing_history_setting" end
            local ok,reason=validate_field(key,v)
            if not ok then return nil,reason end
        end
    end
    if value.remote_notifications then
        return nil,"remote_alert_delivery_not_implemented"
    end
    if value.sampling_enabled and not profile.native_qualified then
        return nil,"native_collector_not_qualified"
    end
    if value.local_alerts_enabled and (not value.sampling_enabled or
       not profile.alerts_qualified) then
        return nil,"local_alert_delivery_not_qualified"
    end
    if value.persist_enabled and
       (not value.sampling_enabled or not profile.storage_qualified) then
        return nil,"persistent_history_not_qualified"
    end
    if value.persist_enabled and value.retention_days==0 then
        return nil,"persistent_retention_required"
    end
    if not value.persist_enabled and value.retention_days~=0 then
        return nil,"retention_requires_qualified_storage"
    end
    if value.rx_low_dbm~=nil then
        if not profile.optics_qualified or not value.sampling_enabled then
            return nil,"optical_threshold_not_qualified"
        end
        if value.rx_low_dbm<profile.rx_min_dbm or
           value.rx_low_dbm>profile.rx_max_dbm then
            return nil,"threshold_outside_board_profile"
        end
    end
    if value.heavy_probe_seconds>0 and not profile.native_qualified then
        return nil,"heavy_native_probe_not_qualified"
    end
    -- Worst case for *two* fixed read-only PON and host subprocesses.
    -- 3s PON + 4s Ethernet per subprocess, without concurrent coalescing.
    -- This is an offline conservative budget, NOT a measured CPU duty cycle.
    local pon=3600/value.pon_interval_seconds
    local host=3600/value.host_interval_seconds
    local heavy=value.heavy_probe_seconds>0 and
        3600/value.heavy_probe_seconds or 0
    local worst_seconds=pon*3+host*4+heavy*5
    if worst_seconds>720 then
        return nil,"probe_budget_exceeds_residential_limit"
    end
    return true,{pon_calls_per_hour=pon,host_calls_per_hour=host,
        optical_reads_per_hour=3600/value.optical_interval_seconds,
        heavy_calls_per_hour=heavy,
        worst_case_command_seconds_per_hour=worst_seconds,
        worst_case_command_duty_fraction=worst_seconds/3600,
        ram_sample_slots=value.ram_sample_limit,
        ram_event_slots=value.ram_event_limit,
        routine_flash_writes_per_day_upper_bound=value.persist_enabled
           and math.floor(86400/value.flush_interval_seconds) or 0,
    }
end
local function check_state(state)
    if type(state)~="table" or state.schema~=1 or
       not integer(state.revision,1,9007199254740990) or
       type(state.values)~="table" then
        return nil,"invalid_preferences_state"
    end
    -- Existing state is validated on every operation; reject corruption.
    local profile={kind="source_only",native_qualified=true,
        optics_qualified=true,storage_qualified=true,
        alerts_qualified=true,rx_min_dbm=-35,rx_max_dbm=-5}
    local good=validate_values(state.values,profile)
    if not good then return nil,"invalid_preferences_state" end
    return true
end
function M.preview(state,patch,expected_revision,profile)
    local valid,reason=check_state(state)
    if not valid then return nil,reason end
    if not integer(expected_revision,1,9007199254740990) or
       expected_revision~=state.revision then
        return nil,"stale_preferences_revision"
    end
    local trusted,why=caps(profile)
    if not trusted then return nil,why end
    if type(patch)~="table" then return nil,"invalid_preference_patch" end
    local fields=0
    for key,value in pairs(patch) do
        fields=fields+1
        if fields>17 then return nil,"too_many_preference_fields" end
        local accepted,err=validate_field(key,value)
        if not accepted then return nil,err end
    end
    if fields==0 then return nil,"empty_preference_patch" end
    local candidate=copy(state.values)
    for key,value in pairs(patch) do
        if key=="rx_low_dbm" and value==false then
            candidate[key]=nil
        else
            candidate[key]=value
        end
    end
    local accepted,metrics=validate_values(candidate,trusted)
    if not accepted then return nil,metrics end
    local changes={}
    for key in pairs(KNOWN) do
        if state.values[key]~=candidate[key] then
            changes[#changes+1]=key
        end
    end
    table.sort(changes)
    if #changes==0 then return nil,"no_effective_setting_change" end
    return {
        schema=1,source_only_not_live=true,preview_only=true,
        hardware_capability_proof=false,
        no_device_write=true,no_service_restart=true,
        no_alert_sent=true,no_flash_write=true,
        revision_before=state.revision,
        revision_after=state.revision+1,
        changed_fields=changes,
        values=candidate,metrics=metrics,
        event_delivery="not_installed",
        external_alert_delivery="unsupported",
        stored_persistence="not_installed",
    }
end

-- Memory-only simulated apply. Never invokes a real config setter.
function M.simulate(state,patch,expected_revision,profile)
    local plan,err=M.preview(state,patch,expected_revision,profile)
    if not plan then return nil,err end
    return {
        schema=1,revision=plan.revision_after,
        values=copy(plan.values),
        source_only_not_live=true,no_device_write=true,
    },plan
end

-- A compact source-only field catalogue for future residential settings
-- UI. Capability flags are test inputs, not proof of a running service.
local FIELD_CATALOG={
    {id="sampling_enabled",label="Collect local history",
     group="basic",type="boolean",requires="native_qualified"},
    {id="pon_interval_seconds",label="PON status interval",
     group="basic",type="choice",options={30,60,120,300}},
    {id="host_interval_seconds",label="Ethernet counter interval",
     group="basic",type="choice",options={30,60,120,300}},
    {id="ram_sample_limit",label="RAM samples",
     group="basic",type="integer",minimum=30,maximum=720},
    {id="ram_event_limit",label="RAM events",
     group="basic",type="integer",minimum=16,maximum=256},
    {id="local_alerts_enabled",label="Local event alerts",
     group="basic",type="boolean",requires="alerts_qualified"},
    {id="optical_interval_seconds",label="Optical sensor interval",
     group="advanced",type="choice",options={60,120,300}},
    {id="heavy_probe_seconds",label="Heavy diagnostic interval",
     group="advanced",type="choice",options={0,300,900},
     requires="native_qualified"},
    {id="persist_enabled",label="Keep compact history across reboots",
     group="advanced",type="boolean",requires="storage_qualified"},
    {id="retention_days",label="Persistent retention target",
     group="advanced",type="choice",options={0,7,30,90},
     requires="storage_qualified"},
    {id="flush_interval_seconds",label="Flash summary interval",
     group="advanced",type="choice",options={900,1800,3600,7200}},
    {id="alert_pon_changes",label="PON state alerts",
     group="advanced",type="boolean"},
    {id="alert_host_changes",label="Ethernet link alerts",
     group="advanced",type="boolean"},
    {id="alert_gaps",label="Missing sample alerts",
     group="advanced",type="boolean"},
    {id="alert_reboots",label="Reboot alerts",
     group="advanced",type="boolean"},
    {id="rx_low_dbm",label="Low optical receive power threshold",
     group="advanced",type="optional_half_dbm",
     requires="optics_qualified"},
    {id="remote_notifications",label="Remote notifications",
     group="advanced",type="boolean",requires="not_implemented"},
}
function M.describe(profile)
    local typed,err=caps(profile)
    if not typed then return nil,err end
    local list={}
    for _,item in ipairs(FIELD_CATALOG) do
        local row={}
        for k,v in pairs(item) do
            if k=="options" then
                local values={}
                for _,option in ipairs(v) do values[#values+1]=option end
                row.options=values
            else row[k]=v end
        end
        row.available=item.requires==nil or
            (item.requires~="not_implemented" and
             typed[item.requires]==true)
        if not row.available then
            row.unavailable_reason=item.requires=="not_implemented"
                and "delivery_not_implemented" or
                "not_hardware_qualified"
        end
        list[#list+1]=row
    end
    return {
        schema=1,fields=list,profile="synthetic_source_only",
        no_real_setting_save=true,hardware_qualification_unverified=true,
    }
end

function M.source_profile()
    return {
        kind="source_only",
        native_qualified=false,optics_qualified=false,
        storage_qualified=false,alerts_qualified=false,
    }
end
return M
