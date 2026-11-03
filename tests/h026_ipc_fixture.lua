-- H-026 vendor-MIPS true cross-process JSON snapshot fixture.
-- All native input synthetic, no actual ONU, real customer data or routing.
local root=assert(arg[1],"vendor rootfs")
local history=assert(arg[2],"source history")
local overlay=assert(arg[3],"source overlay")
local lock_dir=assert(arg[4],"private lock directory")
local ipc_dir=assert(arg[5],"private snapshot directory")
local action=assert(arg[6],"test action")

package.path=history.."/?.lua;"..overlay.."/?.lua;"..
    root.."/usr/lib/lua/?.lua;"..
    root.."/usr/lib/lua/?/init.lua;"..package.path
package.cpath=root.."/usr/lib/lua/?.so;"..package.cpath

local ipc=require "8311.history_snapshot_ipc"
local endpoint=require "8311.history_http_readonly"
local prefs=require "8311.history_preferences"
local guarded=require "8311.history_guarded_collector"
local json=require "luci.jsonc"
local checked=0
local function ok(cond,description)
    checked=checked+1
    assert(cond,"H026_IPC_FIXTURE_FAILED:"..description)
end
local function eq(a,b,label) ok(a==b,label) end
local route={method="GET",route="/admin/8311/history_data"}
local function auth() return true end

if action=="read" or action=="read_invalid" then
    local body,err=ipc.read(ipc_dir,"offline_synthetic")
    if action=="read_invalid" then
        eq(body,nil,"invalid_or_missing_snapshot_refused")
        ok(type(err)=="string" and #err>0,"error_is_bounded")
        local reply=endpoint.serve_offline_ipc(route,auth,ipc_dir)
        eq(reply.status,503,"no_corrupt_data_sent")
        eq(reply.body,'{"error":"history_not_available"}',
           "error_does_not_echo_raw_data")
        print("AOTT_H026_INVALID_READ_DENIED")
    else
        ok(type(body)=="string" and #body>100,"bounded_history_read")
        local result=json.parse(body)
        eq(result.kind,"aott_source_only_history","real_projector_json")
        eq(result.source_only_not_live,true,"source_only_snapshot")
        eq(result.actual_isp_uptime_unverified,true,"no_isp_health_claim")
        eq(result.history_is_volatile,true,"only_volatile_source")
        ok(result.samples[#result.samples].host_link_observation=="observed" or
           result.samples[#result.samples].host_link_observation=="not_sampled",
           "last_host_state_honestly_reported")
        local reply=endpoint.serve_offline_ipc(route,auth,ipc_dir)
        eq(reply.status,200,"verified_authentication_reads_snapshot")
        eq(reply.body,body,"exact_sanitized_content")
        eq(reply.headers["Cache-Control"],"no-store, private, max-age=0",
           "no_store_cache_header")
        eq(reply.headers["X-Content-Type-Options"],"nosniff",
           "content_sniffing_blocked")
        ok(not body:find("11111111-2222",1,true),
           "private_boot_identity_excluded")
        print("AOTT_H026_CROSS_PROCESS_READ_PASS checks="..checked)
    end
    return
end
if action~="publish" and action~="republish" and
   action~="stale_stage" and action~="publish_blocked" and
   action~="publish_denied" then
    error("invalid_offline_fixture_action")
end
local cap={kind="source_only",native_qualified=true}
local configured=assert(prefs.simulate(prefs.defaults(),{
    sampling_enabled=true,pon_interval_seconds=60,
    host_interval_seconds=120,
},1,cap))
local owner,why=guarded.new(lock_dir,configured,cap,"offline_synthetic")
assert(owner,why)
local denied,reason=ipc.publish(nil,ipc_dir,"offline_synthetic")
eq(denied,nil,"no_publication_without_owner")
eq(reason,"exclusive_collector_owner_required","owner_is_required")
denied,reason=ipc.publish(owner,ipc_dir,"production")
eq(denied,nil,"cannot_publish_live")
eq(reason,"snapshot_write_not_authorized","production_mode_rejected")
local provider={clock=100,commands=0}
local boot="11111111-2222-4333-8444-555555555555"
function provider.read(path,max)
    if path=="/proc/sys/kernel/random/boot_id" then return boot.."\n" end
    if path=="/proc/uptime" then
        return tostring(provider.clock).." 19.50\n"
    end
    if path=="/sys/class/net/eth0_0/speed" then return "10000\n" end
    error("unknown_synthetic_kernel_path")
end
function provider.run(argv,max)
    provider.commands=provider.commands+1
    local cmd=table.concat(argv," ")
    if cmd=="/usr/bin/timeout -k 1 3 /usr/bin/pon psg" then
        return 0,"current=51\n",false
    elseif cmd=="/usr/bin/timeout -k 1 4 /usr/sbin/ethtool -S eth0_0" then
        local value=math.floor(provider.clock*1250000)
        return 0,"RxGoodBytes: "..tostring(value)..
            "\nTxGoodBytes: "..tostring(value*2).."\n",false
    end
    error("unknown_synthetic_native_call")
end
for _,at in ipairs({100,160,220}) do
    provider.clock=at
    local sample=assert(guarded.tick(owner,at,provider))
    eq(sample.status,"sample_accepted","simulated_telemetry_sample")
end
eq(provider.commands,5,"one_due_command_per_channel")
if action=="republish" then
    provider.clock=280
    local refreshed=assert(guarded.tick(owner,280,provider))
    eq(refreshed.status,"sample_accepted","fourth_source_tick")
end
if action=="publish_denied" then
    local refused,why=ipc.publish(owner,ipc_dir,"offline_synthetic")
    eq(refused,nil,"unsafe_target_cannot_be_replaced")
    ok(why=="unsafe_snapshot_inode" or
       why=="unsafe_snapshot_directory" or
       why=="stale_snapshot_stage_blocks_publish",
       "dangerous_filesystem_state_rejected")
    assert(guarded.close(owner))
    print("AOTT_H026_PUBLICATION_DENIED")
    return
end
local blocked,err=ipc.read(ipc_dir,"production")
eq(blocked,nil,"read_production_mode_blocked")
eq(err,"snapshot_read_not_authorized","cannot_read_live")
if action=="publish_blocked" then
    local rejected,why=ipc.publish(owner,ipc_dir,"offline_synthetic")
    eq(rejected,nil,"stale_stage_blocks_publish")
    eq(why,"stale_snapshot_stage_blocks_publish",
       "existing_stage_never_overwritten")
    local cleaned,issue=ipc.discard_stale_stage(owner,ipc_dir,"offline_synthetic")
    ok(cleaned~=nil,"stage_cleanup_requires_owner")
    eq(cleaned.status,"verified_stale_stage_discarded","stage_cleaned")
elseif action=="stale_stage" then
    local unpublished,error_code=ipc.publish(owner,ipc_dir,"offline_synthetic")
    eq(unpublished,nil,"symlink_stage_not_followed")
    eq(error_code,"stale_snapshot_stage_blocks_publish","stale_stage_refused")
    local stale,issue=ipc.discard_stale_stage(owner,ipc_dir,"offline_synthetic")
    eq(stale,nil,"unsafe_stage_cannot_be_deleted")
    eq(issue,"unsafe_stale_stage","symlink_stage_refused_to_delete")
    assert(guarded.close(owner))
    print("AOTT_H026_UNSAFE_STAGE_FAIL_CLOSED")
    return
end
local info,why=ipc.publish(owner,ipc_dir,"offline_synthetic")
assert(info,why)
eq(info.status,"offline_atomic_snapshot_verified",
   "atomic_publish_verified")
ok(info.bytes>100 and info.bytes<=65536,"bounded_payload")
eq(info.no_onu_flash_write,true,"no_ono_firmware_write")
eq(info.on_device_tmpfs_qualified,false,"storage_not_board_qualified")
eq(info.no_device_or_isp_contact,true,"no_live_pon")
local encoded=assert(ipc.read(ipc_dir,"offline_synthetic"))
local parsed=json.parse(encoded)
eq(parsed.kind,"aott_source_only_history","parsed_view")
eq(parsed.range,"hour","one_fixed_projection")
eq(#parsed.samples,action=="republish" and 4 or 3,
   "bounded_observed_sample_count")
eq(parsed.samples[2].host_link_observation,"not_sampled",
   "unscheduled_is_not_failed")
eq(parsed.samples[3].elapsed_seconds,120,"exact_real_counter_window")
eq(parsed.windows.hour.rx.covered_seconds,120,"weighted_history_coverage")
eq(parsed.actual_isp_uptime_unverified,true,"no_isp_claim")
ok(not encoded:find(boot,1,true),"boot_uuid_not_exported")
ok(not encoded:find("RxGoodBytes",1,true),"raw_counter_not_exported")
local response=endpoint.serve_offline_ipc(route,auth,ipc_dir)
eq(response.status,200,"only_auth_server_response")
eq(response.body,encoded,"fixed_history_content")
eq(response.headers["Content-Type"],"application/json; charset=utf-8",
   "JSON_content_type")
eq(response.headers["Content-Length"],tostring(#encoded),
   "bounded_length")
eq(response.headers["Vary"],"Cookie","session_varies")
eq(response.no_on_demand_native_poll,true,"no_reader_native_polls")
local reads=0
local function read_once()
    reads=reads+1
    return encoded
end
local rejected_auth=endpoint.serve(route,function() return false end,read_once)
eq(rejected_auth.status,403,"unauthenticated_denied")
eq(reads,0,"unauthenticated_never_reads_private_snapshot")
local exception_auth=endpoint.serve(route,function()error("private_session")end,read_once)
eq(exception_auth.status,403,"auth_exception_denied")
ok(not exception_auth.body:find("private_session",1,true),
   "no_session_error_disclosure")
eq(reads,0,"auth_exception_not_read")
local posted=endpoint.serve({
    method="POST",route="/admin/8311/history_data"
},auth,read_once)
eq(posted.status,405,"no_persistent_settings_post")
eq(reads,0,"post_not_read")
local malformed=endpoint.serve({
    method="GET",route="/admin/8311/history_data",
    path="../../etc/passwd"
},auth,read_once)
eq(malformed.status,400,"path_traversal_argument_rejected")
eq(reads,0,"invalid_path_never_read")
local bad_range=endpoint.serve({
    method="GET",route="/admin/8311/history_data",range="ninety_days"
},auth,read_once)
eq(bad_range.status,400,"server_only_fixed_projector_window")
eq(reads,0,"no_extra_native_poll_for_range")
local poisoned=endpoint.serve(route,auth,function()
    return '{"serial":"PRIVATE_SHOULD_NEVER_BECOME_HTTP_BODY"}'
end)
eq(poisoned.status,503,"invalid_JSON_never_relayed")
ok(not poisoned.body:find("PRIVATE_SHOULD",1,true),
   "untrusted_snapshot_text_redacted")
local duplicate=endpoint.serve(route,auth,function()
    return encoded:sub(1,#encoded-1)..'x'
end)
eq(duplicate.status,503,"corrupt_snapshot_payload_never_relayed")
local sneaky=endpoint.serve(route,auth,function()
    return encoded.."PRIVATE_TRAILING_TEXT"
end)
eq(sneaky.status,503,"JSON_parser_trailing_content_blocked")
ok(not sneaky.body:find("PRIVATE_TRAILING",1,true),
   "no_trailing_text_leaked")
local authorized=endpoint.serve(route,auth,read_once)
eq(authorized.status,200,"trusted_server_auth")
eq(reads,1,"single_trusted_snapshot_read")
eq(authorized.body,encoded,"exact_snapshot_bytes")
assert(guarded.close(owner))
print("AOTT_H026_IPC_PUBLISH_PASS checks="..checked)
