-- H-026: Strict, dependency-free history snapshot shape validation.
-- Runs under host Lua 5.1 and extracted vendor MIPS Lua.
local root=assert(arg[1],"source history root required")
package.path=root.."/?.lua;"..package.path
local sampler=require "8311.history_sampler"
local exporter=require "8311.history_export"
local shape=require "8311.history_snapshot_shape"
local checks=0
local function ok(value,name)
    checks=checks+1
    assert(value,"H026_SHAPE_FIXTURE_FAILED:"..name)
end
local function eq(a,b,name) ok(a==b,name) end
local state=assert(sampler.new({max_samples=120,max_events=128}))
local boot="11111111-2222-4333-8444-555555555555"
for i,time in ipairs({100,160,220,280}) do
    local snapshot={
        boot=boot,source="eth0_0",uptime=time,
        pon_state=i<3 and 51 or 60,
        ethernet_mbps=10000,
        eth={
            RxGoodBytes=tostring(math.floor(time*1250000)),
            TxGoodBytes=tostring(math.floor(time*2500000)),
        },
        serial="SENSITIVE_DO_NOT_EXPORT",
        loid="PRIVATE_DO_NOT_EXPORT",
    }
    local observed=assert(sampler.ingest(state,snapshot))
    eq(observed.samples_retained,i,"source_count_"..i)
end
local function fresh()
    return assert(exporter.project(state,"hour",100))
end
local p=fresh()
local valid,why=shape.validate(p)
eq(valid,true,"actual_projector_shape")
eq(why,nil,"no_schema_error")
eq(p.actual_isp_uptime_unverified,true,"not_wan_uptime")
eq(p.history_is_volatile,true,"volatile_truth")
eq(#p.samples,4,"four_retained_samples")
eq(#p.events,1,"true_PON_change_event")
ok(p.samples[1].boot==nil,"private_boot_not_exported")
ok(p.samples[1].serial==nil,"private_pon_serial_not_exported")
ok(p.samples[1].loid==nil,"private_registration_data_not_exported")
ok(p.samples[1].eth==nil,"raw_counters_not_exported")
eq(shape.MAX_BYTES,65536,"shared_size_cap")

local function reject(label,edit)
    local altered=fresh()
    edit(altered)
    local accepted=shape.validate(altered)
    eq(accepted,nil,label)
end
local cases={
    {"root_new_secret",function(d)d.password="HIDDEN"end},
    {"root_wrong_kind",function(d)d.kind="live_history"end},
    {"root_proves_live",function(d)d.source_only_not_live=false end},
    {"root_proves_wan",function(d)d.actual_isp_uptime_unverified=false end},
    {"root_proves_persistence",function(d)d.history_is_volatile=false end},
    {"root_omits_history_proof",function(d)d.history_is_volatile=nil end},
    {"root_wrong_range",function(d)d.range="lifetime"end},
    {"root_optical_claim",function(d)d.optics_history_unavailable=false end},
    {"root_clock_claim",function(d)d.calendar_time_unverified=false end},
    {"root_write_claim",function(d)d.no_firmware_or_device_write=false end},
    {"root_wrong_units",function(d)d.rate_units="MB/s"end},
    {"root_wrong_max",function(d)d.max_export_items=1000 end},
    {"root_bounded_flag",function(d)d.raw_event_export_is_bounded=false end},
    {"window_hidden_field",function(d)d.windows.hour.boot="secret"end},
    {"window_missing",function(d)d.windows.month=nil end},
    {"window_extra",function(d)d.windows.century={}end},
    {"window_claim_complete",function(d)d.windows.hour.window_complete=true end},
    {"window_proves_isp",function(d)d.windows.hour.full_internet_availability_proven=true end},
    {"window_proves_hardware",function(d)d.windows.hour.hardware_resource_qualified=true end},
    {"window_wrong_duration",function(d)d.windows.hour.requested_window_seconds=86400 end},
    {"window_bad_rate",function(d)d.windows.hour.rx.average_mbps=-1 end},
    {"window_nan",function(d)d.windows.hour.rx.average_mbps=0/0 end},
    {"window_fraction_above_one",function(d)d.windows.hour.rx.coverage_fraction=1.1 end},
    {"sample_private_id",function(d)d.samples[1].loid="secret"end},
    {"sample_raw_counter",function(d)d.samples[1].RxGoodBytes="123"end},
    {"sample_wrong_boot_epoch",function(d)d.samples[1].epoch_index=0 end},
    {"sample_bad_interface",function(d)d.samples[1].source="../config"end},
    {"sample_invalid_status",function(d)d.samples[1].status="WAN_OK"end},
    {"sample_missing_source",function(d)d.samples[1].source=nil end},
    {"sample_invalid_availability",function(d)d.samples[1].pon_observation="down"end},
    {"sample_rate_bad_status",function(d)d.samples[2].status="baseline"end},
    {"sample_negative_rate",function(d)d.samples[2].rx_mbps=-1 end},
    {"event_bad_kind",function(d)d.events[1].kind="subscriber_auth"end},
    {"event_private_mac",function(d)d.events[1].mac="00:00"end},
    {"event_missing_epoch",function(d)d.events[1].epoch_index=nil end},
    {"event_unbounded_window",function(d)d.events[1].observation_window_seconds=1e15 end},
    {"event_bad_channel",function(d)d.events[1].channels="internet"end},
    {"more_than_100_samples",function(d)
        for i=5,101 do d.samples[i]=d.samples[1] end
    end},
    {"extra_array_index",function(d)d.samples[100]="SENSITIVE"end},
    {"missing_arrays",function(d)d.samples=nil end},
}
for _,entry in ipairs(cases) do
    reject(entry[1],entry[2])
end
local again,reason=shape.validate(fresh())
eq(again,true,"all_negative_cases_do_not_corrupt_source")
ok(checks>=50,"complete_fixture")
print("AOTT_H026_PROJECTION_SHAPE_PASS checks="..checks)
