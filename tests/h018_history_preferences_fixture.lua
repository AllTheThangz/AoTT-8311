-- H-018 source-only residential monitoring preferences.
-- Synthetic settings, with no real setting writes or alert delivery.
local module=assert(arg[1],"Preferences model required")
local preferences=assert(loadfile(module))()
local checked=0
local function ok(condition,label)
    checked=checked+1
    assert(condition,"H018_SOURCE_FIXTURE_FAILED:"..label)
end
local function eq(a,b,label) ok(a==b,label) end
local default=preferences.defaults()
local source_caps=preferences.source_profile()
local theoretical={
    kind="source_only",
    native_qualified=true,
    optics_qualified=true,
    storage_qualified=true,
    alerts_qualified=true,
    rx_min_dbm=-29,rx_max_dbm=-8,
}
eq(default.schema,1,"schema")
eq(default.revision,1,"initial_revision")
eq(default.values.sampling_enabled,false,"no_sampler_by_default")
eq(default.values.persist_enabled,false,"no_flash_by_default")
eq(default.values.remote_notifications,false,"no_remote_alerts_by_default")
eq(default.values.local_alerts_enabled,false,"no_local_alerts_by_default")
eq(default.values.retention_days,0,"volatile_history_only")
eq(default.values.heavy_probe_seconds,0,"no_heavy_polling_by_default")
eq(default.values.rx_low_dbm,nil,"no_board_threshold_by_default")
eq(default.values.ram_sample_limit,120,"bounded_default_samples")
eq(default.values.ram_event_limit,128,"bounded_default_events")
eq(default.values.flush_interval_seconds,1800,"default_30min_flush_when_qualified")
eq(source_caps.native_qualified,false,"source_profile_not_qualified")
eq(source_caps.optics_qualified,false,"optics_not_qualified")
eq(source_caps.storage_qualified,false,"storage_not_qualified")
eq(source_caps.alerts_qualified,false,"alerts_not_qualified")
local plan,why=preferences.preview(default,{pon_interval_seconds=120},1,source_caps)
ok(plan~=nil,"source_only_interval_preview")
eq(plan.metrics.worst_case_command_seconds_per_hour,330,"conservative_budget_330")
eq(plan.metrics.pon_calls_per_hour,30,"lower_pon_poll_count")
eq(plan.metrics.host_calls_per_hour,60,"default_host_poll_count")
eq(plan.metrics.optical_reads_per_hour,30,"default_optical_poll_count")
eq(plan.values.pon_interval_seconds,120,"interval_planned")
eq(default.values.pon_interval_seconds,60,"original_remains_unchanged")
eq(plan.preview_only,true,"source_preview_only")
eq(plan.no_device_write,true,"no_real_device_write")
eq(plan.no_flash_write,true,"no_real_flash_write")
eq(plan.no_alert_sent,true,"no_alert_sent")
eq(plan.hardware_capability_proof,false,"caps_do_not_prove_hardware")
eq(plan.external_alert_delivery,"unsupported","external_alert_not_implemented")
eq(plan.stored_persistence,"not_installed","no_installed_storage")
eq(#plan.changed_fields,1,"only_one_changed_field")
eq(plan.changed_fields[1],"pon_interval_seconds","field_name")
local next_state,receipt=assert(preferences.simulate(default,
    {pon_interval_seconds=120},1,source_caps))
eq(next_state.revision,2,"in_memory_revision_increments")
eq(next_state.values.pon_interval_seconds,120,"in_memory_update_only")
eq(default.revision,1,"source_revision_unchanged")
eq(default.values.pon_interval_seconds,60,"source_values_unchanged")
eq(receipt.revision_after,2,"preview_revision_after")
eq(next_state.no_device_write,true,"no_io_on_simulate")
local revised=assert(preferences.preview(next_state,
    {ram_sample_limit=720,ram_event_limit=256},2,source_caps))
eq(revised.values.ram_sample_limit,720,"max_720_ram_sample_slots")
eq(revised.values.ram_event_limit,256,"max_256_ram_event_slots")
eq(revised.metrics.ram_event_slots,256,"right_cap_reported")
eq(revised.metrics.routine_flash_writes_per_day_upper_bound,0,
   "disabled_persistence_no_flash_budget")

local function reject(state,changes,version,caps,code,label)
    local prior_state=state.revision
    local prior_pon=state.values.pon_interval_seconds
    local prior_alert=state.values.local_alerts_enabled
    local result,error_code=preferences.preview(state,changes,version,caps)
    eq(result,nil,label.."_rejected")
    eq(error_code,code,label.."_error")
    eq(state.revision,prior_state,label.."_no_revision_change")
    eq(state.values.pon_interval_seconds,prior_pon,
       label.."_no_source_value_change")
    eq(state.values.local_alerts_enabled,prior_alert,
       label.."_no_alert_change")
end

reject(default,{sampling_enabled=true},1,source_caps,
    "native_collector_not_qualified","unqualified_sampler")
reject(default,{persist_enabled=true,retention_days=7},1,source_caps,
    "persistent_history_not_qualified","unqualified_storage")
reject(default,{retention_days=90},1,source_caps,
    "retention_requires_qualified_storage","retention_without_storage")
reject(default,{rx_low_dbm=-20},1,source_caps,
    "optical_threshold_not_qualified","unqualified_optical_threshold")
reject(default,{local_alerts_enabled=true},1,source_caps,
    "local_alert_delivery_not_qualified","local_alert_requires_native")
reject(default,{remote_notifications=true},1,source_caps,
    "remote_alert_delivery_not_implemented","no_external_notifications")
reject(default,{heavy_probe_seconds=300},1,source_caps,
    "heavy_native_probe_not_qualified","no_unqualified_heavy_poll")
reject(default,{pon_interval_seconds=30,host_interval_seconds=30},
    1,source_caps,"probe_budget_exceeds_residential_limit",
    "unsafe_fast_polling")
reject(default,{pon_interval_seconds=15},1,source_caps,
    "invalid_sample_interval","faster_than_min_supported")
reject(default,{pon_interval_seconds=0},1,source_caps,
    "invalid_sample_interval","zero_poll_interval")
reject(default,{optical_interval_seconds=30},1,source_caps,
    "invalid_optical_interval","optical_too_fast")
reject(default,{heavy_probe_seconds=60},1,source_caps,
    "invalid_heavy_probe_interval","heavy_too_fast")
reject(default,{flush_interval_seconds=30},1,source_caps,
    "invalid_flash_cadence","flash_wear_guard")
reject(default,{ram_sample_limit=721},1,source_caps,
    "invalid_ram_sample_limit","samples_above_cap")
reject(default,{ram_event_limit=257},1,source_caps,
    "invalid_ram_event_limit","events_above_cap")
reject(default,{ram_event_limit=1},1,source_caps,
    "invalid_ram_event_limit","events_below_min")
reject(default,{ram_sample_limit=2},1,source_caps,
    "invalid_ram_sample_limit","samples_below_min")
reject(default,{retention_days=365},1,source_caps,
    "invalid_retention_days","unqualified_one_year")
reject(default,{pon_interval_seconds="60"},1,source_caps,
    "invalid_sample_interval","numeric_string_rejected")
reject(default,{sampling_enabled="true"},1,source_caps,
    "invalid_boolean","string_true_rejected")
reject(default,{sampling_enabled=1},1,source_caps,
    "invalid_boolean","number_true_rejected")
reject(default,{__index="not_allowed"},1,source_caps,
    "unknown_history_setting","unknown_key_injection")
reject(default,{hostname="sensitive"},1,source_caps,
    "unknown_history_setting","secret_endpoint_rejected")
reject(default,{rx_low_dbm=-20.1},1,source_caps,
    "invalid_rx_low_threshold","unsupported_threshold_step")
reject(default,{rx_low_dbm=-40},1,source_caps,
    "invalid_rx_low_threshold","threshold_below_generic_bound")
reject(default,{ram_sample_limit=0/0},1,source_caps,
    "invalid_ram_sample_limit","nan_memory")
reject(default,{ram_sample_limit=math.huge},1,source_caps,
    "invalid_ram_sample_limit","inf_memory")
reject(default,{pon_interval_seconds=120},2,source_caps,
    "stale_preferences_revision","concurrent_stale_revision")
reject(default,{},1,source_caps,
    "empty_preference_patch","empty_patch")
reject(default,nil,1,source_caps,
    "invalid_preference_patch","missing_patch")
reject(default,{pon_interval_seconds=120},1,nil,
    "invalid_source_profile","missing_profile")

local bad_caps={kind="device",native_qualified=true}
reject(default,{pon_interval_seconds=120},1,bad_caps,
    "invalid_source_profile","unknown_profile_type")
bad_caps={kind="source_only",other_feature=true}
reject(default,{pon_interval_seconds=120},1,bad_caps,
    "unknown_capability","capability_injection")
bad_caps={kind="source_only",native_qualified="yes"}
reject(default,{pon_interval_seconds=120},1,bad_caps,
    "invalid_capability","untyped_capability")
bad_caps={kind="source_only",optics_qualified=true}
reject(default,{pon_interval_seconds=120},1,bad_caps,
    "unsupported_optical_profile","optical_missing_profile")
bad_caps={kind="source_only",optics_qualified=false,rx_min_dbm=-30}
reject(default,{pon_interval_seconds=120},1,bad_caps,
    "unqualified_optical_profile","optical_unqualified_bounds")

-- All optional features are permitted only in a *synthetic* verified
-- capability scenario. Even this mode never writes or sends an alert.
local both=assert(preferences.preview(default,{
    sampling_enabled=true,local_alerts_enabled=true,
    persist_enabled=true,retention_days=90,flush_interval_seconds=3600,
    rx_low_dbm=-20,heavy_probe_seconds=300,
    alert_pon_changes=false,alert_host_changes=true,
},1,theoretical))
eq(both.values.sampling_enabled,true,"synthetic_native_sampling")
eq(both.values.persist_enabled,true,"synthetic_persistence")
eq(both.values.retention_days,90,"synthetic_90day_selection")
eq(both.values.local_alerts_enabled,true,"synthetic_local_alert")
eq(both.values.rx_low_dbm,-20,"synthetic_optical_threshold")
eq(both.metrics.routine_flash_writes_per_day_upper_bound,24,
   "hourly_flash_upper_bound")
eq(both.preview_only,true,"still_preview_even_with_capabilities")
eq(both.hardware_capability_proof,false,"capabilities_not_attestation")
eq(both.event_delivery,"not_installed","local_alert_not_running")
eq(both.external_alert_delivery,"unsupported","no_remote_alert_adapter")
eq(both.stored_persistence,"not_installed","no_real_store")
local hypothetical=assert(preferences.simulate(default,{
    sampling_enabled=true,local_alerts_enabled=true,
    persist_enabled=true,retention_days=90,flush_interval_seconds=3600,
    rx_low_dbm=-20
},1,theoretical))
eq(hypothetical.values.rx_low_dbm,-20,"threshold_set_in_memory")
local cleared=assert(preferences.preview(hypothetical,{
    rx_low_dbm=false,local_alerts_enabled=false,
    persist_enabled=false,retention_days=0,
},2,theoretical))
eq(cleared.values.rx_low_dbm,nil,"explicit_threshold_clear")
eq(cleared.values.persist_enabled,false,"persistence_disabled_in_preview")
eq(cleared.values.retention_days,0,"retention_disabled_in_preview")
reject(default,{sampling_enabled=true,persist_enabled=true,
    retention_days=0},1,theoretical,
    "persistent_retention_required","storage_requires_retention")
reject(default,{sampling_enabled=true,rx_low_dbm=-7},1,theoretical,
    "threshold_outside_board_profile","threshold_above_qualified_band")
reject(default,{sampling_enabled=true,rx_low_dbm=-30},1,theoretical,
    "threshold_outside_board_profile","threshold_below_qualified_band")
reject(default,{sampling_enabled=true,rx_low_dbm=-20,
    remote_notifications=true},1,theoretical,
    "remote_alert_delivery_not_implemented",
    "remote_delivery_stays_blocked_with_profile")

-- A thousand in-memory previews and staged changes do not write anything.
local current=preferences.defaults()
for i=1,1000 do
    local requested=i%2==0 and 60 or 120
    local next,report=preferences.simulate(current,{
        pon_interval_seconds=requested,
    },current.revision,source_caps)
    ok(next~=nil,"1000_memory_only_stages_"..tostring(i))
    ok(report.no_device_write and report.no_flash_write,
       "1000_no_writes_"..tostring(i))
    ok(report.no_alert_sent,"1000_no_alert_delivery_"..tostring(i))
    eq(current.revision,i,"1000_old_revision_untouched_"..tostring(i))
    current=next
end
eq(current.revision,1001,"revision_advanced_1000_in_memory")
eq(current.values.sampling_enabled,false,"still_not_collecting")
eq(current.values.persist_enabled,false,"still_not_persisting")
eq(current.values.remote_notifications,false,"still_not_notifying")
-- Every proposed setting is discoverable without inventing a working
-- backend. Unqualified capabilities remain explicitly unavailable.
local schema=assert(preferences.describe(source_caps))
eq(schema.schema,1,"field_schema_version")
eq(#schema.fields,17,"all_17_fields_discoverable")
eq(schema.no_real_setting_save,true,"source_only_no_save")
eq(schema.hardware_qualification_unverified,true,"no_hardware_proof")
local by_id={}
for _,field in ipairs(schema.fields) do
    ok(by_id[field.id]==nil,"field_id_unique_"..field.id)
    by_id[field.id]=field
    ok(field.group=="basic" or field.group=="advanced",
       "field_group_"..field.id)
    ok(type(field.label)=="string" and #field.label>0,
       "field_label_"..field.id)
end
eq(by_id.sampling_enabled.available,false,"native_disabled_in_source")
eq(by_id.persist_enabled.available,false,"persistence_disabled_in_source")
eq(by_id.local_alerts_enabled.available,false,"local_alert_disabled_in_source")
eq(by_id.rx_low_dbm.available,false,"optical_threshold_disabled_in_source")
eq(by_id.remote_notifications.available,false,"remote_not_implemented")
eq(by_id.remote_notifications.unavailable_reason,
   "delivery_not_implemented","remote_block_reason")
eq(by_id.pon_interval_seconds.available,true,"interval_preview_editable")
eq(by_id.ram_event_limit.maximum,256,"event_schema_limit")
eq(by_id.ram_sample_limit.maximum,720,"sample_schema_limit")
eq(by_id.flush_interval_seconds.options[1],900,"flash_min_cadence")
eq(by_id.optical_interval_seconds.options[1],60,"optical_min_interval")
local simulated=assert(preferences.describe(theoretical))
eq(simulated.fields[1].available,true,"synthetic_board_profile_allows_preview")
eq(simulated.fields[#simulated.fields].available,false,
   "remote_stays_disabled_in_synthetic_board")
local mutated=schema.fields[2].options
mutated[1]=1
local again=assert(preferences.describe(source_caps))
eq(again.fields[2].options[1],30,"schema_options_not_shared_between_calls")
local invalid_schema,invalid_schema_reason=preferences.describe({kind="invalid"})
eq(invalid_schema,nil,"schema_invalid_profile_rejected")
eq(invalid_schema_reason,"invalid_source_profile","schema_profile_reason")
reject(default,{pon_interval_seconds=60},1,source_caps,
    "no_effective_setting_change","no_op_staging_rejected")

ok(checked>=3000,"full_fixture_checks")
print("AOTT_H018_SOURCE_PREFERENCES_FIXTURE_PASS checks="..checked)
