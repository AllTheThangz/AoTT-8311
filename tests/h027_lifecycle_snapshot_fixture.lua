-- H-027 actual extracted-vendor MIPS lifecycle-to-IPC integration.
-- Fixed synthetic native provider. No live PON or ONU commands.
local vendor=assert(arg[1],"vendor rootfs")
local history=assert(arg[2],"source history")
local overlay=assert(arg[3],"source overlay")
local lockdir=assert(arg[4],"private lock directory")
local snapdir=assert(arg[5],"private snapshot directory")
local mode=assert(arg[6],"fixture mode")
package.path=history.."/?.lua;"..overlay.."/?.lua;"..
    vendor.."/usr/lib/lua/?.lua;"..vendor.."/usr/lib/lua/?/init.lua;"..
    package.path
package.cpath=vendor.."/usr/lib/lua/?.so;"..package.cpath

local prefs=require "8311.history_preferences"
local life=require "8311.history_lifecycle"
local ipc=require "8311.history_snapshot_ipc"
local endpoint=require "8311.history_http_readonly"
local json=require "luci.jsonc"
local checks=0
local BOOT_A="11111111-2222-4333-8444-555555555555"
local BOOT_B="22222222-3333-4444-8555-666666666666"
local function ok(value,name)
    checks=checks+1
    assert(value,"H027_LIFECYCLE_SNAPSHOT_FAILED:"..name)
end
local function eq(a,b,name) ok(a==b,name) end
local route={method="GET",route="/admin/8311/history_data"}
local function admin() return true end
local function anonymous() return false end
local function read_checked()
    local data,info=ipc.read_guarded(snapdir,lockdir,"offline_synthetic")
    return data,info
end
-- H-028: deliberately hold ONLY the preexisting main collector lock
-- around a crashed writer's stale snapshot. H-027 would grant HTTP 200
-- here despite no verified new publisher. The second gate must reject.
if mode=="raw_lock_hold" then
    local lock=require "8311.history_process_lock"
    local owner=assert(lock.acquire(lockdir))
    local gate=require "8311.history_publication_gate"
    eq(gate.reader_admitted(lockdir,"offline_synthetic"),false,
       "no_publication_admission_from_main_lock")
    eq(read_checked(),nil,"old_cache_denied_even_with_main_owner")
    print("AOTT_H028_MAIN_LOCK_WITHOUT_PUBLICATION")
    io.stdout:flush()
    io.read("*l")
    assert(lock.release(owner))
    print("AOTT_H028_MAIN_LOCK_RELEASED")
    return
end
if mode=="reader" or mode=="reader_denied" then
    local data,info=read_checked()
    local reply=endpoint.serve_guarded_offline_ipc(route,admin,
                                                   snapdir,lockdir)
    if mode=="reader_denied" then
        eq(data,nil,"no_read_without_producer_lock")
        eq(reply.status,503,"no_http_200_without_producer_lock")
        ok(type(info)=="string" and #info>0,"bounded_owner_error")
        print("AOTT_H027_READER_DENIED")
    else
        ok(type(data)=="string" and #data>400,
           "separate_process_obtains_bounded_cache")
        eq(info.guard_owner_checked_before_and_after,true,
           "double_guard_verification")
        eq(info.publication_gate_checked_before_and_after,true,
           "publication_gate_verified_on_each_read")
        eq(info.producer_runtime_freshness_not_qualified,true,
           "lock_owner_not_equivalent_to_freshness")
        eq(reply.status,200,"trusted_admin_reads_cached_projection")
        eq(reply.body,data,"unchanged_validated_snapshot_bytes")
        eq(reply.no_on_demand_native_poll,true,
           "http_does_not_run_pon")
        eq(json.parse(data).actual_isp_uptime_unverified,true,
           "ISP_uptime_not_proven")
        local refused=endpoint.serve_guarded_offline_ipc(
            route,anonymous,snapdir,lockdir)
        eq(refused.status,403,"unauthorized_session_denied")
        print("AOTT_H027_READER_PASS checks="..checks)
    end
    return
end

local cap={kind="source_only",native_qualified=true}
local values=assert(prefs.simulate(prefs.defaults(),{
    sampling_enabled=true,pon_interval_seconds=60,
    host_interval_seconds=30,
},1,cap))
local session,meta=assert(life.new(lockdir,values,cap,
                                   "offline_synthetic"))
local start=assert(life.status(session))
eq(start.snapshot_source_enabled,false,
   "snapshot_not_enabled_by_default")
local configure=assert(life.configure_snapshot(session,snapdir,
                                               "offline_synthetic"))
eq(configure.no_collector_started,true,"configure_is_inert")
eq(life.configure_snapshot(session,snapdir,"offline_synthetic"),
   nil,"snapshot_config_cannot_be_repeated")
eq(life.configure_snapshot(session,"/tmp/unsafe","offline_synthetic"),
   nil,"disallowed_directory_rejected")
local not_started,reason=read_checked()
eq(not_started,nil,"no_unstarted_snapshot")
local started,why=life.start(session,100)
if mode=="unsafe_stage" then
    eq(started,nil,"symlink_stale_stage_blocks_start")
    eq(why,"snapshot_stale_stage_unverified",
       "unsafe_stage_has_explicit_error")
    eq(assert(life.status(session)).phase,"unsafe",
       "invalid_stage_fails_closed")
    eq(endpoint.serve_guarded_offline_ipc(route,admin,snapdir,lockdir).status,
       503,"invalid_stage_keeps_unauthenticated_snapshot_unavailable")
    print("AOTT_H027_UNSAFE_STAGE_BLOCKS_START")
    return
end
eq(assert(started).status,"running","explicit_guarded_source_start")
eq(life.configure_snapshot(session,snapdir,"offline_synthetic"),
   nil,"cannot_mutate_running_snapshot_path")
if mode=="start_only_hold" then
    -- No old snapshot may remain visible before the first new sample.
    eq(read_checked(),nil,"new_owner_start_revokes_prior_cache")
    print("AOTT_H027_START_WITHOUT_SNAPSHOT")
    io.stdout:flush()
    io.read("*l")
    eq(assert(life.shutdown(session)).phase,"closed",
       "close_new_owner_without_sampling")
    print("AOTT_H027_SOURCE_STOP_PASS checks="..checks)
    return
end
local provider={uptime=100,boot=BOOT_A,commands=0}
function provider.read(path,max)
    if path=="/proc/sys/kernel/random/boot_id" then
        return provider.boot.."\n"
    elseif path=="/proc/uptime" then
        return tostring(provider.uptime).." 10.0\n"
    elseif path=="/sys/class/net/eth0_0/speed" then
        return "10000\n"
    end
    error("unexpected_source_read")
end
function provider.run(argv,max)
    provider.commands=provider.commands+1
    local cmd=table.concat(argv," ")
    if cmd=="/usr/bin/timeout -k 1 3 /usr/bin/pon psg" then
        return 0,"current=51\n",false
    elseif cmd=="/usr/bin/timeout -k 1 4 /usr/sbin/ethtool -S eth0_0" then
        local rx=math.floor(provider.uptime*1250000)
        return 0,"RxGoodBytes: "..tostring(rx)..
            "\nTxGoodBytes: "..tostring(rx*2).."\n",false
    end
    error("unexpected_native_argv")
end
local function sample(at)
    provider.uptime=at
    return assert(life.step(session,at,provider))
end
local first=sample(100)
if mode=="publication_unsafe" then
    eq(first.status,"cooldown",
       "invalid_or_competing_publication_gate_causes_cooldown")
    eq(first.snapshot_publish_failures,1,
       "rejected_publication_admission_counted")
    eq(first.verified_snapshot_reader_admitted,false,
       "no_unsafe_publisher_admitted")
    eq(read_checked(),nil,"no_cache_served_after_gate_failure")
    eq(endpoint.serve_guarded_offline_ipc(route,admin,snapdir,lockdir).status,
       503,"HTTP_refuses_invalid_publisher_gate")
    print("AOTT_H028_PUBLISH_ADMISSION_REFUSED")
    return
end
eq(first.status,"sample_accepted","first_source_sample")
eq(first.verified_snapshot_reader_admitted,true,
   "only_verified_published_snapshot_admitted")
eq(first.snapshot_publish_status,"verified_offline_snapshot",
   "first_sample_published")
eq(first.snapshots_published,1,"one_snapshot")
eq(first.snapshot_last_source_uptime,100,"snapshot_source_clock")
eq(provider.commands,2,"first_native_read_only_once")
local initial=assert(read_checked())
eq(#json.parse(initial).samples,1,"first_snapshot_one_sample")

local early=sample(110)
eq(early.status,"not_due","early_sample_not_read_again")
eq(provider.commands,2,"early_poll_no_extra_commands")
local host_only=sample(130)
eq(host_only.status,"sample_accepted","host_only_observed")
eq(host_only.snapshot_publish_status,"not_due",
   "no_snapshot_write_before_60s")
eq(host_only.snapshots_published,1,"no_frequent_snapshot_churn")
eq(provider.commands,3,"one_host_read_due")
local still=assert(read_checked())
eq(still,initial,"unchanged_snapshot_before_due")
local subsequent=sample(160)
eq(subsequent.status,"sample_accepted","second_published_tick")
eq(subsequent.snapshot_publish_status,"verified_offline_snapshot",
   "next_snapshot_after_60s")
eq(subsequent.snapshots_published,2,"two_bounded_snapshots")
local updated=assert(read_checked())
ok(updated~=initial,"new_snapshot_is_atomic_replacement")
eq(#json.parse(updated).samples,3,"three_actual_observations")
eq(provider.commands,5,"no_extra_native_reads_for_snapshot")
eq(assert(life.status(session)).snapshots_published,2,
   "snapshot_count_in_receipt")
local http=endpoint.serve_guarded_offline_ipc(route,admin,snapdir,lockdir)
eq(http.status,200,"active_source_owner_proves_read_admission")
eq(http.body,updated,"HTTP_current_snapshot")
eq(endpoint.serve_guarded_offline_ipc(route,anonymous,snapdir,lockdir).status,
   403,"admin_session_required")
local malformed=endpoint.serve_guarded_offline_ipc({
    method="POST",route="/admin/8311/history_data"
},admin,snapdir,lockdir)
eq(malformed.status,405,"no_settings_mutations_through_GET")

if mode=="reboot" then
    provider.boot=BOOT_B
    local reboot=sample(2)
    eq(reboot.status,"sample_accepted","boot_reset_verified_by_H021")
    eq(reboot.history_status,"reboot","true_reboot_event")
    eq(reboot.snapshot_publish_status,"verified_offline_snapshot",
       "publish_new_boot_without_clock_overlap")
    local latest=json.parse(assert(read_checked()))
    eq(#latest.samples,1,"no_old_boot_samples_in_new_epoch")
    eq(latest.events[1].kind,"reboot_observed",
       "boot_observation_recorded")
elseif mode=="corrupt_stage" then
    local f=assert(io.open(snapdir.."/snapshot.json.new","w"))
    f:write("deliberately interrupted source stage")
    f:close()
    local fs=require "nixio.fs"
    assert(fs.chmod(snapdir.."/snapshot.json.new",600))
    local next_tick=sample(220)
    eq(next_tick.status,"cooldown",
       "failed_snapshot_publish_causes_guarded_cooldown")
    eq(next_tick.owns_kernel_lock,false,
       "failed_writer_drops_kernel_lock")
    eq(next_tick.snapshot_publish_failures,1,
       "publication_failure_counted")
    eq(read_checked(),nil,
       "stale_source_not_servable_after_publisher_failure")
    eq(endpoint.serve_guarded_offline_ipc(route,admin,snapdir,lockdir).status,
       503,"http_fails_closed_after_publisher_error")
    eq(assert(life.shutdown(session)).phase,"closed",
       "shutdown_cooldown_safely")
    print("AOTT_H027_PUBLISH_FAILURE_SAFE checks="..checks)
    return
elseif mode=="invalid_stop" then
    local target=snapdir.."/snapshot.json"
    local fs=require "nixio.fs"
    assert(fs.chmod(target,644))
    local stopped,why=life.stop(session)
    eq(stopped,nil,"cannot_claim_successful_invalidated_cache")
    eq(why,"snapshot_invalidation_failed","stop_failure_explicit")
    eq(assert(life.status(session)).phase,"unsafe",
       "failed_cache_invalidation_freezes_session")
    eq(endpoint.serve_guarded_offline_ipc(route,admin,snapdir,lockdir).status,
       503,"orphan_cache_not_servable")
    print("AOTT_H027_INVALID_STOP_SAFE checks="..checks)
    return
end

print("AOTT_H027_SOURCE_PUBLISH_READY checks="..checks)
io.stdout:flush()
if mode=="hold" or mode=="crash" then
    io.read("*l")
end
if mode=="crash" then
    print("AOTT_H027_UNCLEAN_EXIT_WITH_CACHE")
    os.exit(0)
end
local stopped=assert(life.shutdown(session))
eq(stopped.phase,"closed","explicit_shutdown")
eq(read_checked(),nil,"stop_revokes_guarded_snapshot")
eq(endpoint.serve_guarded_offline_ipc(route,admin,snapdir,lockdir).status,
   503,"HTTP_after_clean_stop_is_unavailable")
print("AOTT_H027_SOURCE_STOP_PASS checks="..checks)
