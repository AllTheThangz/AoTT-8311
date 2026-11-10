local overlay=assert(arg[1],"overlay root required")
package.path=overlay.."/?.lua;"..package.path

local lock=require "8311.history_process_lock"
local snapshot=require "8311.history_live_snapshot"
local sampler=require "8311.history_sampler"

assert(lock.PRODUCTION_DIR=="/var/run/aott-history")
local state=assert(sampler.new({max_samples=30,max_events=16}))
local function row(t,rx,tx)
    return {
        boot="11111111-2222-4333-8444-555555555555",
        uptime=t,source="eth0_0",pon_state=51,ethernet_mbps=10000,
        eth={RxGoodBytes=tostring(rx),TxGoodBytes=tostring(tx)},
        observed={pon=true,host=true},
    }
end
assert(sampler.ingest_selected(state,row(100,1000000,2000000)))
assert(sampler.ingest_selected(state,row(160,61000000,122000000)))

local owner=assert(lock.acquire(lock.PRODUCTION_DIR))
assert(snapshot.invalidate(owner))
local published=assert(snapshot.publish(owner,state))
assert(published.status=="history_runtime_snapshot_verified")
local denied,why=snapshot.read_guarded()
assert(denied==nil)
assert(why=="publication_gate_missing_or_unsafe" or why=="no_verified_publisher")
local publication=assert(snapshot.admit())
local body,info=assert(snapshot.read_guarded())
assert(type(body)=="string" and #body>10)
assert(body:find('"kind":"aott_local_history"',1,true))
assert(info.guard_owner_checked_before_and_after==true)
assert(info.publication_gate_checked_before_and_after==true)
assert(snapshot.revoke(publication))
local stale,stale_why=snapshot.read_guarded()
assert(stale==nil)
assert(stale_why=="no_verified_publisher" or stale_why=="publication_gate_missing_or_unsafe")
assert(snapshot.invalidate(owner))
assert(lock.release(owner))
local absent,absent_why=snapshot.read_guarded()
assert(absent==nil)
assert(absent_why=="no_guarded_writer")
print("AOTT_V3_HISTORY_PRODUCTION_LOCK_PASS")
