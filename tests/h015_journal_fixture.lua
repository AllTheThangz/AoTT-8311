-- H-015 deterministic power-cut, wear-cadence and bounded persistence model.
-- All storage is an in-memory fake; no files, commands or live hardware.
local module=assert(arg[1],"Source module path required")
local journal=assert(loadfile(module))()
local checks=0
local function ok(value,name)
    checks=checks+1
    assert(value,"H015_MODEL_FIXTURE_FAILED:"..name)
end
local function eq(actual,expected,name)
    ok(actual==expected,name)
end
local function event(epoch,time,kind,from,to,extra)
    local r={
        type="event",epoch_index=epoch,at_uptime=time,
        event_kind=kind,from=from,to=to,
        observation_window_seconds=10,
        walltime_trust="unknown",
        serial="SYNTHETIC_NEVER_EMIT",loid="SYNTHETIC_SECRET",
        raw_output="SYNTHETIC_UNTRUSTED_LINE"
    }
    if extra then for k,v in pairs(extra) do r[k]=v end end
    return r
end
local function summary(epoch,time,walltime,rx,tx)
    return {
        type="hourly_summary",epoch_index=epoch,at_uptime=time,
        rate_source="host_ethernet_byte_counters",
        walltime_trust=walltime and "verified" or "unknown",
        walltime_unix=walltime,
        rx_average_mbps=rx,tx_average_mbps=tx,
        rx_covered_seconds=rx and 3500 or 0,
        tx_covered_seconds=tx and 3450 or 0,
        sample_count=55,
        serial="SYNTHETIC_NEVER_EMIT",
        raw_output="SYNTHETIC_UNTRUSTED_LINE",
    }
end
local function store()
    local v={A=nil,B=nil,replacements=0,reads=0,mode=nil}
    local a={
        read_slot=function(slot)
            assert(slot=="A" or slot=="B")
            v.reads=v.reads+1
            if v.mode=="throw_read" then error("simulated_storage_error") end
            if v.mode=="unknown_read" then return nil,"unavailable" end
            if v[slot]==nil then return nil,"missing" end
            return v[slot]
        end,
        replace_slot=function(slot,image)
            assert(slot=="A" or slot=="B")
            v.replacements=v.replacements+1
            if v.mode=="throw_write" then error("simulated_write_interruption") end
            if v.mode=="torn" then
                v[slot]=image:sub(1,math.floor(#image/2))
                return true
            end
            if v.mode=="false_success" then
                v[slot]=image:sub(1,17)
                return true
            end
            if v.mode=="reject" then return false end
            v[slot]=image
            return true
        end,
    }
    return a,v
end
eq(journal.MAX_SLOT_BYTES,163840,"slot_limit_160KiB")
eq(journal.MAX_LOGICAL_BYTES,491520,"two_slots_one_temp_under_512KiB")
eq(journal.MIN_FLUSH_SECONDS,900,"min_15min")
eq(journal.MAX_EVENTS,256,"event_record_cap")
eq(journal.MAX_HOURLY_SUMMARIES,2160,"90days_hourly_cap")
local adapter,files=store()
local state,meta=assert(journal.recover(adapter))
eq(meta.state,"empty","fresh_empty_store")
eq(state.sequence,0,"new_generation_zero")
eq(files.replacements,0,"no_startup_flash_write")
local inspected=assert(journal.inspect(state,20))
eq(inspected.records_returned,0,"initial_no_records")
eq(inspected.proved_90_day_retention,false,"no_unproven_retention")
eq(inspected.cross_boot_walltime_verified,false,"clock_unverified")
local input=event(1,100,"pon_state_change",51,60)
local accepted=assert(journal.append(state,input))
eq(accepted.accepted,true,"accepted_first_event_in_ram")
eq(accepted.no_flash_write,true,"append_only_ram")
eq(files.replacements,0,"append_has_no_storage_side_effect")
local fail,reason=journal.flush(state,adapter,1,100)
eq(fail,nil,"early_flush_refused")
eq(reason,"routine_write_deferred","15min_cadence_guard")
eq(files.replacements,0,"no_early_write")
local first=assert(journal.flush(state,adapter,1,900))
eq(first.active_slot,"A","first_checkpoint_A")
eq(first.sequence,1,"first_checkpoint_sequence")
eq(first.verified_atomic_filesystem_semantics,false,"no_unproven_fs_durability")
eq(first.hardware_flash_wear_unverified,true,"wear_not_hardware_proven")
eq(first.source_only_not_deployed,true,"source_not_live")
eq(files.replacements,1,"one_write_only")
eq(files.A~=nil,true,"A_contents_exist")
local decoded=assert(journal.unpack(files.A))
eq(decoded.sequence,1,"decoded_generation")
eq(decoded.record_count,1,"one_checkpoint_record")
eq(decoded.records[1].code,"P","compact_event_kind")
local fresh,found=assert(journal.recover(adapter))
eq(found.state,"recovered_single_slot","recovered_A")
eq(found.active_slot,"A","selected_A")
eq(found.sequence,1,"recovered_seq1")
inspected=assert(journal.inspect(fresh,20))
eq(inspected.records_returned,1,"recovered_one_event")
eq(inspected.records[1].event_kind,"pon_state_change","event_kind_roundtrip")
eq(inspected.records[1].from,51,"from_roundtrip")
eq(inspected.records[1].to,60,"to_roundtrip")
eq(inspected.records[1].walltime_trust,"unknown","no_fake_walltime")
ok(not files.A:find("SYNTHETIC_NEVER_EMIT",1,true),"private_serial_not_in_checkpoint")
ok(not files.A:find("SYNTHETIC_SECRET",1,true),"private_credential_not_in_checkpoint")
ok(not files.A:find("raw_output",1,true),"raw_device_output_not_checkpointed")
local prior=#files.A
local rejected,why=journal.append(fresh,event(1,99,"pon_state_change",60,51))
eq(rejected,nil,"monotonic_event_guard")
eq(why,"nonmonotonic_history_record","monotonic_error")
eq(#files.A,prior,"invalid_event_no_storage_side_effect")
local valid=assert(journal.append(fresh,event(1,1000,"host_link_change",10000,0)))
eq(valid.records,2,"second_event_appended")
fail,reason=journal.flush(fresh,adapter,1,1500)
eq(fail,nil,"flush_before_15min_since_checkpoint")
eq(reason,"routine_write_deferred","same_boot_cadence")
eq(files.replacements,1,"no_extra_flash_write")
local second=assert(journal.flush(fresh,adapter,1,1800))
eq(second.active_slot,"B","second_to_other_slot")
eq(second.sequence,2,"second_generation")
eq(files.replacements,2,"one_commit_for_second_checkpoint")
local two,info=assert(journal.recover(adapter))
eq(info.state,"two_valid_checkpoints","two_good_slots")
eq(two.active,"B","highest_generation_wins")
eq(#two.records,2,"both_rows_recovered")
local newer=files.B
files.B=files.B:sub(1,25)
local fallback,fallback_info=assert(journal.recover(adapter))
eq(fallback.active,"A","torn_B_falls_back_to_A")
eq(fallback.sequence,1,"recovered_prior_generation")
eq(#fallback.records,1,"uncommitted_new_event_not_in_old_slot")
files.B=newer
local unauthorized=files.B:gsub("checksum=","checksum=00000000")
ok(unauthorized~=files.B,"checksum_corruption_fixture_changed_bytes")
files.B=unauthorized
fallback=assert(journal.recover(adapter))
eq(fallback.active,"A","bad_checksum_rolls_back_to_A")
files.B=newer
local both_bad=files.A
files.A=files.A:sub(1,10)
files.B=files.B:sub(1,13)
fail,reason=journal.recover(adapter)
eq(fail,nil,"both_corrupt_recovery_stops")
eq(reason,"no_valid_history_checkpoint","no_silent_history_reinitialize")
files.A=both_bad
files.B=newer

-- Unexpected store exceptions never cause silent fresh initialization.
files.mode="throw_read"
fail,reason=journal.recover(adapter)
eq(fail,nil,"read_error_fails_closed")
eq(reason,"journal_storage_unavailable","read_error_code")
files.mode="unknown_read"
fail=journal.recover(adapter)
eq(fail,nil,"unknown_read_cannot_be_called_missing")
files.mode=nil

-- A write that tears the alternate slot must leave the old image intact.
local running=assert(journal.recover(adapter))
assert(journal.append(running,event(1,2000,"observation_unavailable",nil,nil)))
files.mode="torn"
fail,reason=journal.flush(running,adapter,1,2700)
eq(fail,nil,"torn_write_rejected")
eq(reason,"checkpoint_readback_unverified","torn_readback_error")
eq(running.uncertain,true,"unsafe_writer_frozen_after_torn")
fail,reason=journal.flush(running,adapter,1,3600)
eq(fail,nil,"frozen_writer_refuses_retry")
eq(reason,"unsafe_history_state","write_requires_recovery")
local safe=assert(journal.recover(adapter))
eq(safe.sequence,2,"old_valid_B_survives_torn_A")
eq(safe.active,"B","prior_B_preserved")
files.mode=nil
assert(journal.append(safe,event(1,2000,"sampling_gap",nil,nil)))
local third=assert(journal.flush(safe,adapter,1,2700))
eq(third.sequence,3,"new_commit_after_explicit_recovery")
eq(third.active_slot,"A","third_alternating_slot")

-- A new boot epoch requires 15 min of *new boot* uptime and cannot blend
-- old monotonic measurements with another boot's history.
local state4=assert(journal.recover(adapter))
assert(journal.append(state4,event(2,100,"reboot_observed")))
fail,reason=journal.flush(state4,adapter,2,800)
eq(fail,nil,"no_immediate_reboot_flash_churn")
eq(reason,"routine_write_deferred","new_boot_minimum")
local reboot_commit=assert(journal.flush(state4,adapter,2,900))
eq(reboot_commit.sequence,4,"new_boot_can_commit_after_cadence")
local snapshot=assert(journal.recover(adapter))
eq(snapshot.write_epoch,2,"boot_epoch_persisted_as_number")
inspected=assert(journal.inspect(snapshot,50))
eq(inspected.records[#inspected.records].type,"event","reboot_event_kept")
eq(inspected.records[#inspected.records].event_kind,"reboot_observed","reboot_marker")
ok(inspected.records[#inspected.records].walltime_unix==nil,
   "no_calendar_time_inferred_from_monotonic")

-- Two valid copies with identical generation but divergent contents
-- require operator reconciliation rather than arbitrary selection.
local alien=assert(journal.pack(
    {assert(journal.unpack(files.A)).records[1]},4,2,900000))
files.A=alien
fail,reason=journal.recover(adapter)
eq(fail,nil,"duplicate_generation_conflict")
eq(reason,"ambiguous_history_generation","generation_conflict_error")
print("AOTT_H015_JOURNAL_FIXTURE_STAGE1_PASS checks="..checks)

-- Exact 90-day *hourly* summary-capacity experiment with a verified
-- synthetic wall clock. It does not claim a real device ran for 90 days.
local long_adapter,long_files=store()
local history=assert(journal.recover(long_adapter))
local first_wall=1760000000
for i=1,2160 do
    local record=summary(1,i*3600,first_wall+i*3600,12.345,4.567)
    local value,err=journal.append(history,record)
    ok(value~=nil,"hourly_summary_"..tostring(i)..":"..tostring(err))
end
eq(#history.records,2160,"exact_2160_hourly_entries")
eq(long_files.replacements,0,"many_aggregates_still_RAM_only")
local hour_end=2160*3600
local first_long,first_error=journal.flush(history,long_adapter,1,hour_end+900)
ok(first_long~=nil,"first_90day_checkpoint_"..tostring(first_error))
eq(first_long.evicted_on_size_limit,0,"2160_normal_summary_rows_fit")
eq(first_long.records,2160,"full_hourly_count_saved")
ok(#long_files.A<=journal.MAX_SLOT_BYTES,"under_per_slot_budget")
ok(#long_files.A>100000,"meaningful_high_cardinality_fixture")
local restored=assert(journal.recover(long_adapter))
eq(#restored.records,2160,"2160_hourly_rows_recovered")
local rows=assert(journal.inspect(restored,100))
eq(rows.retained_total,2160,"retained_total_vs_100_export_cap")
eq(rows.records_returned,100,"max_100_export")
eq(rows.records[#rows.records].type,"hourly_summary","last_hour_row")
eq(rows.records[#rows.records].rx_average_mbps,12.345,"rx_precision_milli")
eq(rows.records[#rows.records].tx_average_mbps,4.567,"tx_precision_milli")
eq(rows.records[#rows.records].walltime_trust,"verified","walltime_explicit_only")
eq(rows.proved_90_day_retention,false,"synthetic_retention_not_hardware_proof")
ok(not long_files.A:find("SYNTHETIC_NEVER_EMIT",1,true),
   "no_private_identifier_in_large_checkpoint")
ok(not long_files.A:find("raw_output",1,true),
   "no_raw_telemetry_in_large_checkpoint")
local old=assert(journal.inspect(restored,1)).records[1].at_uptime
local last_hour=hour_end+3600
assert(journal.append(restored,summary(1,last_hour,
    first_wall+last_hour,12.3,4.5)))
eq(#restored.records,2160,"oldest_summary_evicted_at_2161")
eq(restored.evicted,1,"bounded_summary_eviction_count")
eq(assert(journal.inspect(restored,1)).records[1].at_uptime,
   last_hour,"newest_summary_at_tail")

-- Even a burst of 300 state events is capped at 256 while retaining the
-- last events and leaving old reliable checkpoints untouched.
local event_start=last_hour+3600
for i=1,300 do
    local x=event(1,event_start+i*10,"pon_state_change",51,60,
       {walltime_trust="verified",walltime_unix=first_wall+event_start+i*10})
    local value=journal.append(restored,x)
    ok(value~=nil,"300_event_capacity_"..tostring(i))
end
local event_count,summary_count=0,0
for _,v in ipairs(restored.records) do
    if v.type=="event" then event_count=event_count+1
    else summary_count=summary_count+1 end
end
eq(event_count,256,"event_type_hard_cap")
ok(summary_count<=2160,"hourly_type_hard_cap")
ok(#restored.records<=journal.MAX_EVENTS+journal.MAX_HOURLY_SUMMARIES,
   "combined_number_bounded")
local flush_time=event_start+3000+900
local long_commit,long_reason=journal.flush(restored,long_adapter,1,flush_time)
ok(long_commit~=nil,"large_checkpoint_fits_eviction_"..tostring(long_reason))
eq(long_commit.active_slot,"B","second_long_checkpoint_to_B")
eq(long_commit.sequence,2,"second_long_checkpoint_generation")
ok(#long_files.B<=journal.MAX_SLOT_BYTES,"still_under_160KiB_slot")
ok(3*journal.MAX_SLOT_BYTES<=512*1024,"3_physical_logical_footprints")
local long_copy=assert(journal.recover(long_adapter))
rows=assert(journal.inspect(long_copy,100))
eq(rows.records_returned,100,"large_source_still_100_export_cap")
eq(rows.records[#rows.records].type,"event","latest_is_event")
eq(rows.records[#rows.records].event_kind,"pon_state_change",
   "latest_event_kind")
eq(rows.records[#rows.records].walltime_trust,"verified",
   "explicit_verified_event_clock")
eq(rows.records[#rows.records].at_uptime,event_start+3000,
   "last_event_at_correct_uptime")

-- Invalid sources, impossible coverage and untrusted timestamp flags
-- cannot be persisted or elevate a clock from unknown to verified.
local bad_state=assert(journal.recover(long_adapter))
local dirty_before=bad_state.dirty
local accepted_before=#bad_state.records
local last_record=bad_state.records[#bad_state.records]
local function reject_input(input,label)
    local value=journal.append(bad_state,input)
    eq(value,nil,label)
    eq(#bad_state.records,accepted_before,label.."_no_mutation")
    eq(bad_state.dirty,dirty_before,label.."_no_dirty_state")
end
reject_input(summary(1,last_record.uptime_ms/1000+100,nil,-1,4),
    "negative_rx_avg")
local badsum=summary(1,last_record.uptime_ms/1000+100,nil,12,4)
badsum.rate_source="unqualified_network_counter"
reject_input(badsum,"unqualified_rate_source")
badsum=summary(1,last_record.uptime_ms/1000+100,nil,12,4)
badsum.rx_covered_seconds=3601
reject_input(badsum,"overfull_hourly_coverage")
badsum=summary(1,last_record.uptime_ms/1000+100,nil,12,4)
badsum.walltime_trust="verified"
reject_input(badsum,"trusted_timestamp_without_value")
local badevent=event(1,last_record.uptime_ms/1000+100,"invalid_kind")
reject_input(badevent,"unrecognized_event_kind")
badevent=event(1,last_record.uptime_ms/1000+100,
    "pon_state_change",0,255,{channels="unexpected"})
reject_input(badevent,"unexpected_channel")
badevent=event(1,last_record.uptime_ms/1000+100,
    "pon_state_change",0,255,{observation_window_seconds=-2})
reject_input(badevent,"negative_observation_window")
badevent=event(0,last_record.uptime_ms/1000+100,
    "pon_state_change",0,255)
reject_input(badevent,"invalid_epoch_zero")

-- Invalid backing bytes are not silently accepted, even when their
-- checksum is correctly recalculated over an unsupported version.
local fake=long_files.A:gsub("AOTT15|1|","AOTT15|2|")
ok(fake~=long_files.A,"version_damaged")
local decoded_data=journal.unpack(fake)
eq(decoded_data,nil,"unsupported_version_or_checksum_rejected")
local semantically_bad=long_files.A:gsub("S|1|","X|1|",1)
ok(semantically_bad~=long_files.A,"row_damaged")
decoded_data=journal.unpack(semantically_bad)
eq(decoded_data,nil,"tampered_row_checksum_fails")

-- Adapter errors freeze uncertain writers rather than filling both
-- slots with competing versions after a suspicious write.
local error_adapter,error_files=store()
local tentative=assert(journal.recover(error_adapter))
assert(journal.append(tentative,event(1,910,"reboot_observed")))
error_files.mode="throw_write"
local bad,code=journal.flush(tentative,error_adapter,1,950)
eq(bad,nil,"interrupted_initial_write")
eq(code,"checkpoint_write_unverified","interrupted_write_error")
eq(tentative.uncertain,true,"failed_initial_writer_frozen")
error_files.mode=nil
local still_empty=assert(journal.recover(error_adapter))
eq(still_empty.sequence,0,"no_false_commit_after_error")
print("AOTT_H015_JOURNAL_FIXTURE_PASS checks="..tostring(checks))

-- Calendar queries are anchored to the *latest verified record*, never
-- presented as current time or guaranteed continuous history.
local clean_adapter,clean_files=store()
clean_files.A=long_files.A
local retained=assert(journal.recover(clean_adapter))
local seven=assert(journal.calendar_counts(retained,7))
local thirty=assert(journal.calendar_counts(retained,30))
local ninety=assert(journal.calendar_counts(retained,90))
eq(seven.status,"partial_verified_walltime_evidence","7day_partial_evidence")
eq(seven.hourly_summaries,169,"7day_hourly_bounds_with_inclusive_anchor")
eq(thirty.hourly_summaries,721,"30day_hourly_bounds")
eq(ninety.hourly_summaries,2160,"90day_all_synthetic_hourly_rows")
eq(ninety.change_events,0,"90day_no_unproven_events")
eq(ninety.latest_verified_walltime_unix,
   first_wall+2160*3600,"verified_record_anchor_not_now")
eq(ninety.anchor_source,"latest_explicitly_verified_record_walltime",
   "anchor_provenance")
eq(ninety.current_calendar_time_verified,false,"not_current_walltime")
eq(ninety.full_period_retention_proven,false,"no_90day_retention_claim")
eq(ninety.continuous_collection_proven,false,"no_continuity_claim")
eq(ninety.actual_isp_availability_proven,false,"not_ISP_uptime")
eq(ninety.observed_span_seconds,2159*3600,"verified_sample_span_only")
eq(ninety.unknown_calendar_time_records,0,"all_fixture_hours_explicit")
local none=assert(journal.recover({read_slot=function(slot)
    return nil,"missing"
end,replace_slot=function() return false end}))
assert(journal.append(none,event(1,950,"pon_state_change",51,60)))
local unavailable=assert(journal.calendar_counts(none,90))
eq(unavailable.status,"no_verified_calendar_anchor",
   "missing_NTP_does_not_invent_calendar")
eq(unavailable.hourly_summaries,0,"unknown_clock_excluded")
eq(unavailable.unknown_calendar_time_records,1,"unknown_record_count")
local denied,why=journal.calendar_counts(retained,91)
eq(denied,nil,"unsupported_days")
eq(why,"unsupported_calendar_range","unsupported_days_reason")

-- A caller must not be able to place arbitrary text into a journal by
-- mutating a private record object and bypassing normalize().
local dirty=assert(journal.recover(clean_adapter))
dirty.records[1].rx="MALFORMED"
local encoded,pack_error=journal.pack(
    dirty.records,dirty.sequence+1,1,2161*3600*1000)
eq(encoded,nil,"manually_corrupted_stage_rejected")
eq(pack_error,"invalid_staged_record","stage_record_guard")
print("AOTT_H015_CALENDAR_AND_STAGE_FIXTURE_PASS checks="..checks)
