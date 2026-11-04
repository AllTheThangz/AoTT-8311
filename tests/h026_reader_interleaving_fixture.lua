-- Deterministic H-026 reader interleavings. Vendor-MIPS modules and real
-- filesystem operations; synchronization and injected values are test-only.
local root=assert(arg[1],"vendor rootfs")
local history=assert(arg[2],"history source")
local overlay=assert(arg[3],"overlay source")
local directory=assert(arg[4],"private snapshot directory")
local action=assert(arg[5],"interleaving")
package.path=history.."/?.lua;"..overlay.."/?.lua;"..
    root.."/usr/lib/lua/?.lua;"..root.."/usr/lib/lua/?/init.lua;"..package.path
package.cpath=root.."/usr/lib/lua/?.so;"..package.cpath
local ipc=require "8311.history_snapshot_ipc"
local endpoint=require "8311.history_http_readonly"
local canonical=require "8311.history_export"
local json=require "luci.jsonc"
local n=require "nixio"
local fs=require "nixio.fs"
local path=directory.."/snapshot.json"
local count=0
local function check(condition,label)
    count=count+1
    assert(condition,"H026_INTERLEAVING_FAILED:"..label)
end
local function eq(left,right,label) check(left==right,label) end
local function barrier(point)
    io.write("AOTT_H026_READER_READY:"..point.."\n");io.flush()
    eq(io.read("*l"),"continue","explicit_test_release")
end
local function valid(body,samples)
    check(type(body)=="string" and #body>100 and #body<=65536,"bounded_payload")
    local parsed=assert(json.parse(body))
    eq(canonical.encode_checked_projection(parsed),body,"canonical_whole_snapshot")
    eq(#parsed.samples,samples,"expected_generation")
    eq(parsed.source_only_not_live,true,"source_only")
    eq(parsed.actual_isp_uptime_unverified,true,"no_isp_claim")
    eq(parsed.history_is_volatile,true,"volatile_only")
    check(not body:find("11111111-2222",1,true),"no_private_identity")
    check(not body:find("RxGoodBytes",1,true),"no_raw_counter")
end
local route={method="GET",route="/admin/8311/history_data"}
local function auth() return true end
if action=="between_reads" then
    local previous=assert(ipc.read(directory,"offline_synthetic"))
    valid(previous,3)
    barrier("first_read_complete")
    local reply=endpoint.serve_offline_ipc(route,auth,directory)
    eq(reply.status,200,"second_request_success")
    valid(reply.body,4)
    check(previous~=reply.body,"distinct_generations_are_valid")
    eq(reply.headers["Content-Length"],tostring(#reply.body),"response_length")
    eq(reply.headers["Cache-Control"],"no-store, private, max-age=0","not_cached")
    print("AOTT_H026_DISTINCT_GENERATIONS_PASS checks="..count)
    return
end

local direct=action=="before_open" or action=="before_final_stat"
local http=action=="http_before_open" or action=="http_before_final_stat"
check(direct or http,"recognized_interleaving")
local use_open=action=="before_open" or action=="http_before_open"
local original_open,original_lstat=n.open,fs.lstat
local calls,paused=0,false
if use_open then
    n.open=function(name,...)
        if name==path and not paused then
            paused=true
            barrier("before_open")
        end
        return original_open(name,...)
    end
else
    fs.lstat=function(name,...)
        if name==path then
            calls=calls+1
            if calls==2 then
                paused=true
                barrier("before_final_stat")
            end
        end
        return original_lstat(name,...)
    end
end
local body,reason,reads=nil,nil,0
local function read_once()
    reads=reads+1
    body,reason=ipc.read(directory,"offline_synthetic")
    return body
end
local reply
local ran,problem=pcall(function()
    if http then reply=endpoint.serve(route,auth,read_once)
    else read_once() end
end)
n.open,fs.lstat=original_open,original_lstat
check(ran,"interleaved_read_completed_without_exception")
check(paused,"barrier_was_reached")
eq(reads,1,"exactly_one_snapshot_attempt")
eq(body,nil,"mid_read_replacement_refused")
eq(reason,use_open and "snapshot_inode_changed" or "snapshot_readback_unverified",
   "exact_fail_closed_reason")
if http then
    eq(reply.status,503,"no_mixed_generation_success")
    eq(reply.body,'{"error":"history_not_available"}',"generic_error_only")
    eq(reply.headers["Content-Length"],tostring(#reply.body),"error_length")
    eq(reply.headers["Cache-Control"],"no-store, private, max-age=0","error_not_cached")
end
-- Once publication stops, the same reader must recover without retries,
-- weakened ownership checks or a permanently unavailable response.
local latest=assert(ipc.read(directory,"offline_synthetic"))
valid(latest,4)
local stable=endpoint.serve_offline_ipc(route,auth,directory)
eq(stable.status,200,"subsequent_quiescent_request_succeeds")
eq(stable.body,latest,"same_stable_generation")
print("AOTT_H026_MID_READ_REFUSAL_PASS checks="..count)
