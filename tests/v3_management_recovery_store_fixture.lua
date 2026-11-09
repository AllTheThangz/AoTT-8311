local root=assert(arg[1],"fixture root required")
local overlay=assert(arg[2],"overlay lua root required")
package.path=overlay.."/?.lua;"..package.path
local store=require "8311.management_recovery_store"

local job=string.rep("a",32)
local network="package 'network'\nconfig interface 'lct'\n\toption proto 'static'\n"
local firewall="package 'firewall'\nconfig zone\n\toption name 'lan'\n"
local environment="8311_ipaddr=192.0.2.1\n8311_netmask=255.255.255.0\n"
local dropbear="package 'dropbear'\nconfig dropbear\n\toption DirectInterface 'lct'\n"

local receipt,why=store.arm(root,job,network,firewall,environment,dropbear,"offline_synthetic")
assert(receipt,why)
assert(receipt.status=="MANAGEMENT_RECOVERY_ARMED")
assert(receipt.contains_configuration_values==false)

local pending=assert(store.pending(root,"offline_synthetic"))
assert(pending.pending==true and pending.job_id==job)
assert(#pending.network_sha256==64 and #pending.firewall_sha256==64 and
       #pending.environment_sha256==64 and #pending.dropbear_sha256==64)

local backup=assert(store.load(root,job,"offline_synthetic"))
assert(backup.network==network)
assert(backup.firewall==firewall)
assert(backup.environment==environment)
assert(backup.dropbear==dropbear)

assert(store.confirmed(root,job,"offline_synthetic")==false)
local confirmation=assert(store.confirm(root,job,"offline_synthetic"))
assert(confirmation.status=="MANAGEMENT_CONFIRMATION_RECORDED")
assert(store.confirmed(root,job,"offline_synthetic")==true)
local duplicate=assert(store.confirm(root,job,"offline_synthetic"))
assert(duplicate.status=="MANAGEMENT_CONFIRMATION_RECORDED")
local wrong_confirm,wrong_confirm_why=
    store.confirm(root,string.rep("b",32),"offline_synthetic")
assert(wrong_confirm==nil and wrong_confirm_why=="management_recovery_job_mismatch")

local wrong,wrongwhy=store.load(root,string.rep("b",32),"offline_synthetic")
assert(wrong==nil and wrongwhy=="management_recovery_job_mismatch")

local second,secondwhy=store.arm(root,string.rep("b",32),
    network,firewall,environment,dropbear,"offline_synthetic")
assert(second==nil and secondwhy=="management_recovery_already_pending")

local cleared=assert(store.clear(root,job,"offline_synthetic"))
assert(cleared.status=="MANAGEMENT_RECOVERY_CLEARED")
local none=assert(store.pending(root,"offline_synthetic"))
assert(none.pending==false)

-- Re-arm and corrupt a backup after the marker is committed.
assert(store.arm(root,job,network,firewall,environment,dropbear,"offline_synthetic"))
local p=root.."/ptconf/8311/aott-recovery/v1/management/network.before"
local f=assert(io.open(p,"ab"));f:write("corrupt\n");f:close()
local bad,badwhy=store.pending(root,"offline_synthetic")
assert(bad==nil and badwhy=="management_recovery_backup_digest_mismatch")

print("AOTT_V3_MANAGEMENT_RECOVERY_STORE_PASS")
