-- H-016: bounded JSON and CSV history export tests.
-- Synthetic observations only. No ONU or network access.
local root=assert(arg[1],"Source root required")
package.path=root.."/?.lua;"..package.path
local sampler=require "8311.history_sampler"
local exporter=require "8311.history_export"
local checks=0
local function ok(x,label)
    checks=checks+1
    assert(x,"H016_EXPORT_FIXTURE_FAILED:"..label)
end
local function eq(a,b,label) ok(a==b,label) end
local function sample(boot,t,pon,link,rx,tx)
    return {
        boot=boot,uptime=t,source="eth0_0",
        pon_state=pon,ethernet_mbps=link,
        eth={RxGoodBytes=tostring(rx),TxGoodBytes=tostring(tx)},
    }
end
local state=assert(sampler.new({max_samples=16,max_events=16}))
local empty=assert(exporter.project(state,"hour"))
eq(empty.kind,"aott_source_only_history","project_type")
eq(#empty.samples,0,"empty_samples")
eq(#empty.events,0,"empty_events")
eq(empty.windows.hour.status,"no_retained_samples","empty_window")
eq(empty.history_is_volatile,true,"no_persistence")
eq(empty.actual_isp_uptime_unverified,true,"no_wan_claim")
eq(empty.source_only_not_live,true,"source_only")
local j=assert(exporter.export_json(state,"hour"))
ok(j:find('"samples":[]',1,true)~=nil,"empty_json_samples")
ok(j:find('"events":[]',1,true)~=nil,"empty_json_events")
local csv=assert(exporter.export_csv(state,"hour"))
ok(csv:match("^record_type,at_uptime,source,status,")~=nil,"csv_header")
eq(select(2,csv:gsub("\r\n","")),1,"csv_header_only")
local function accept(entry)
    local result,err=sampler.ingest(state,entry)
    ok(result~=nil,err or "ingest")
    return result
end
accept(sample("boot-A",50,51,10000,0,0))
accept(sample("boot-A",200,51,10000,15000000,7500000))
accept(sample("boot-A",350,60,1000,30000000,15000000))
accept(sample("boot-A",500,nil,1000,45000000,22500000))
accept(sample("boot-A",650,51,1000,60000000,30000000))
accept(sample("boot-A",700,51,1000,65000000,32500000))
local ready=assert(exporter.project(state,"hour",100))
eq(#ready.samples,6,"six_samples")
ok(#ready.events>=2,"independent_events")
eq(ready.windows.hour.samples_considered,6,"observed_history")
eq(ready.windows.hour.rx.interval_count,3,"measured_intervals")
eq(ready.windows.ninety_days.window_complete,false,"no_fake_90days")
eq(ready.optics_history_unavailable,true,"no_fake_optics")
eq(ready.calendar_time_unverified,true,"no_fake_calendar")
eq(ready.raw_tail_independent_of_selected_range,true,"tail_range_switch")
for _,row in ipairs(ready.samples) do
    eq(row.epoch_index,1,"initial_epoch")
    ok(row.boot==nil and row.eth==nil,"no_raw_counter_export")
end
for _,row in ipairs(ready.events) do
    eq(row.epoch_index,1,"event_epoch")
    ok(row.boot==nil and row.raw_output==nil,"no_raw_events")
end
local json=assert(exporter.export_json(state,"hour",100))
csv=assert(exporter.export_csv(state,"hour",100))
ok(#json<=65536 and #csv<=65536,"bounded_export_bytes")
ok(json:find('"windows":',1,true)~=nil,"five_window_json")
ok(json:find('"samples":[',1,true)~=nil,"sample_array")
ok(json:find('"epoch_index":1',1,true)~=nil,"epoch_exposed_not_bootid")
ok(json:find('"boot":',1,true)==nil,"no_boot_uuid_export")
eq(select(2,csv:gsub("\r\n","")),1+#ready.samples+#ready.events,
   "CSV_row_count")
for line in csv:gmatch("([^\r\n]+)") do
    eq(select(2,line:gsub(",","")),11,"CSV_columns_fixed")
end
local shorter=assert(exporter.project(state,"day",3))
eq(#shorter.samples,3,"bounded_tail_limit")
eq(shorter.windows.day.requested_window_seconds,86400,"day_preset")
local longest=assert(exporter.project(state,"ninety_days",100))
eq(#longest.samples,6,"90day_has_same_bounded_tail")
local bad,why=exporter.project(state,"forever",100)
eq(bad,nil,"reject_invalid_range")
eq(why,"invalid_export_range","bad_range_reason")
for _,limit in ipairs({0,101,-1,1.5,"100"}) do
    bad,why=exporter.project(state,"hour",limit)
    eq(bad,nil,"reject_invalid_limit_"..tostring(limit))
    eq(why,"invalid_export_limit","invalid_limit_reason")
end
print("AOTT_H016_EXPORT_FIXTURE_STAGE1_PASS checks="..tostring(checks))

-- A sample ending in the selected one-hour window may contain an
-- interval starting before that window. It must not export partial Mbps.
local spanning=assert(sampler.new({max_samples=8,max_events=8}))
assert(sampler.ingest(spanning,sample("boot-C",50,51,10000,0,0)))
assert(sampler.ingest(spanning,sample("boot-C",200,51,10000,15000000,7500000)))
assert(sampler.ingest(spanning,sample("boot-C",3700,51,10000,365000000,182500000)))
local spanning_view=assert(exporter.project(spanning,"hour"))
eq(#spanning_view.samples,3,"tail_independent_of_hour_cutoff")
eq(spanning_view.windows.hour.excluded_cross_window_intervals,1,
   "cross_window_boundary_not_imputed")
local one_hour=assert(exporter.export_csv(spanning,"hour"))
ok(one_hour:find('"50"',1,true)==nil,"older_sample_excluded")
local crossing=one_hour:match('("sample","200"[^\r\n]+)')
ok(type(crossing)=="string","crossing_sample_present")
ok(crossing:find(',"","",',1,true)~=nil,
   "crossing_rate_cells_blank_not_zero")
local one_day=assert(exporter.export_csv(spanning,"day"))
ok(one_day:find('"50"',1,true)~=nil,"longer_range_restores_old_sample")
local span_json=assert(exporter.export_json(spanning,"hour"))

-- A reboot resets monotonic uptime. The exported event and sample tail
-- must show only the latest private epoch, not older matching timestamps.
accept(sample("boot-B",2,51,10000,0,0))
local rebooted=assert(exporter.project(state,"ninety_days",100))
eq(state.epoch_index,2,"reboot_epoch_increments")
eq(#rebooted.samples,1,"no_previous_boot_samples")
eq(rebooted.samples[1].at_uptime,2,"new_boot_uptime")
eq(rebooted.samples[1].epoch_index,2,"new_epoch_provenance")
eq(#rebooted.events,1,"only_new_boot_marker")
eq(rebooted.events[1].kind,"reboot_observed","reboot_is_not_ISP_outage")
eq(rebooted.events[1].epoch_index,2,"event_latest_epoch_only")
eq(rebooted.windows.ninety_days.rx.average_mbps,nil,
   "cross_reboot_rate_not_invented")
local after_csv=assert(exporter.export_csv(state,"ninety_days"))
ok(after_csv:find('"650"',1,true)==nil,"old_boot_value_not_exported")

-- Interface change and long gap each create their own export epoch.
local changed=sample("boot-B",12,51,1000,1500000,750000)
changed.source="eth1_0"
accept(changed)
eq(state.epoch_index,3,"new_interface_epoch")
local shifted=assert(exporter.project(state,"hour"))
eq(#shifted.samples,1,"old_interface_samples_excluded")
eq(shifted.events[1].kind,"source_changed","source_change_event")
changed=sample("boot-B",3620,51,1000,2500000,850000)
changed.source="eth1_0"
accept(changed)
eq(state.epoch_index,4,"large_gap_epoch")
local gap=assert(exporter.project(state,"hour"))
eq(#gap.samples,1,"old_gap_samples_excluded")
eq(gap.events[1].kind,"sampling_gap","gap_event")
ok(gap.events[1].observation_window_seconds>=3600,
   "gap_time_is_sample_window_not_outage_duration")

-- Reject untrusted state and malformed interface text, rather than
-- allowing it into downloadable JSON or a spreadsheet.
local invalid=assert(sampler.new())
invalid.epoch_index=nil
local success,reason=exporter.export_json(invalid,"hour")
eq(success,nil,"missing_epoch_rejected")
eq(reason,"invalid_export_state","epoch_error")
invalid=assert(sampler.new())
invalid.samples_count=1
invalid.samples[1]={at_uptime=5,status="baseline",source="eth0_0",
    epoch_index=1,extra_field="SHOULD_NOT_BE_EXPORTED"}
success=assert(exporter.export_json(invalid,"hour"))
ok(success:find("extra_field",1,true)==nil,"unlisted_fields_discarded")
invalid.samples[1].source="=1+1"
success=exporter.export_csv(invalid,"hour")
eq(success,nil,"formula_shaped_source_rejected")
ok(checks>=100,"complete_export_fixture")
print("AOTT_H016_EXPORT_FIXTURE_PASS checks="..tostring(checks))
if arg[2]=="emit_json" then
    print("AOTT_H016_JSON_PAYLOAD="..json)
    print("AOTT_H016_SPAN_JSON_PAYLOAD="..span_json)
end
