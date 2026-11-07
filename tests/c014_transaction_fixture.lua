-- Integrated native Lua/UCI stage -> apply -> confirm/independent recovery.
-- Every package is synthetic and both file trees are private fixture paths.
local vendor,repo,root,stage,action=assert(arg[1]),assert(arg[2]),assert(arg[3]),assert(arg[4]),assert(arg[5])
local ttl=tonumber(arg[6]) or 30
local point=arg[7] or "none"
local fault=arg[8] or "none"
local supplied_id=arg[9]
package.path=repo.."/prototypes/configuration/?.lua;"..repo.."/overlay/usr/lib/lua/?.lua;"..
 vendor.."/usr/lib/lua/?.lua;"..vendor.."/usr/lib/lua/?/init.lua;"..package.path
package.cpath=vendor.."/usr/lib/lua/?.so;"..package.cpath
local n,fs=require "nixio",require "nixio.fs"
local web,json=require "8311.webutil",require "luci.jsonc"
local model,tx=require "8311.vlan_transition",require "8311.vlan_transaction"
local s=assert(root:match("^/var/tmp/aott%-c014%-txn%-test%-([a-f0-9]+)$"))
assert(#s==16 and stage:match("^/var/tmp/aott%-c014%-stage%-test%-[a-f0-9]+$"))
local namespace="aott_c014_"..s
local packages={network=namespace.."_network",firewall=namespace.."_firewall"}
local actual_statvfs=fs.statvfs
if fault=="capacity_low" or fault=="inodes_low" or fault=="capacity_missing" or fault=="readonly_storage" then
 fs.statvfs=function(path)
  if fault=="capacity_missing" then return nil end
  local stats=actual_statvfs(path)
  if fault=="capacity_low" then stats.bavail=0
  elseif fault=="inodes_low" then stats.files=100;stats.favail=0
  elseif fault=="readonly_storage" then stats.flag=1 end
  return stats
 end
end
local capture=web.capture
web.capture=function(argv,limit)
 if argv[5]=="/usr/bin/sha256sum" then
  assert(#argv==6 and argv[6]:sub(1,#root+1)==root.."/")
  return capture({"/usr/bin/timeout","-k","1","5","/usr/bin/qemu-mips-static","-L",vendor,
    vendor.."/bin/busybox","sha256sum",argv[6]},limit)
 end
 return capture(argv,limit)
end
local function eq(a,b,label) assert(a==b,"C014_TRANSACTION_FIXTURE:"..label) end
local function same(a,b)
 if type(a)~=type(b) then return false end
 if type(a)~="table" then return a==b end
 for k,v in pairs(a) do if not same(v,b[k]) then return false end end
 for k in pairs(b) do if a[k]==nil then return false end end
 return true
end
local function guard_file(path)
 local st=fs.lstat(path)
 assert(st and st.type=="reg" and st.uid==0 and st.gid==0 and st.modedec==600 and st.nlink==1 and st.size<=65536,
  "UNSAFE_SYNTHETIC_FILE")
end
local function native(config,argv,commit,cold)
 for _,path in ipairs({root,root.."/active",stage,stage.."/candidate",stage.."/delta",stage.."/cold"}) do
  local st=fs.lstat(path);assert(st and st.type=="dir" and st.uid==0 and st.modedec==700,"UNSAFE_FIXTURE_DIR")
 end
 for _,name in pairs(packages) do
  eq(fs.lstat("/tmp/.uci/"..name),nil,"no_default_delta")
  guard_file(config.."/"..name)
 end
 local argv0={"/usr/bin/timeout","-k","1","5","/usr/bin/qemu-mips-static","-L",vendor,
   vendor.."/sbin/uci","-c",config,commit and "-p" or "-P",stage..(cold and "/cold" or "/delta")}
 for _,v in ipairs(argv) do argv0[#argv0+1]=v end
 return capture(argv0,65536)
end
local function one(pkg,cold,active)
 local code,raw,overflow=native(active and root.."/active" or stage.."/candidate",{"export",packages[pkg]},false,cold)
 eq(code,0,"native_export");eq(overflow,false,"native_bound")
 return assert(model.parse_export(raw,packages[pkg]))
end
local function snapshot(cold,active) return {network=one("network",cold,active),firewall=one("firewall",cold,active)} end
local adapter={disposable_fixture=true,transaction_directory=root,workspace_directory=stage,
 source_snapshot=function()return snapshot(true,true)end,
 snapshot=function()return snapshot(false,false)end,
 persisted_snapshot=function()return snapshot(true,false)end,
 applied_readback=function()return snapshot(true,true)end,
 activation_ready=function()return true end}
local operations=0
adapter.command=function(op)
 operations=operations+1
 local verb,operand=op[1],op[2]
 local pkg,tail=operand:match("^([a-z]+)(.*)$");assert(packages[pkg])
 assert(verb=="set" or verb=="delete" or verb=="add_list" or verb=="commit")
 if verb~="commit" then
  local code,raw,overflow=native(stage.."/candidate",{verb,packages[pkg]..tail})
  return code==0 and raw=="" and overflow==false
 end
 eq(tail,"","package_only_commit")
 local expected=one(pkg,false,false)
 local code,raw,overflow=native(stage.."/candidate",{"commit",packages[pkg]},true)
 if code~=0 or raw~="" or overflow~=false or not same(one(pkg,true,false),expected) then return false end
 local path=stage.."/delta/"..packages[pkg]
 if fs.lstat(path) then guard_file(path);assert(fs.unlink(path)) end
 return same(one(pkg,false,false),expected)
end
local function output(result,why)
 if not result then result={status="REJECTED",error=why} end
 result.native_stage_operations=operations
 print(json.stringify(result));io.flush()
end
local function state_phase(path)
 local text=fs.readfile(path,2048)
 return type(text)=="string" and text:match("^AOTT%-C014%-TXN%-[123]\n([^\n]+)\n") or nil
end
local original_rename=fs.rename
local fired=false
fs.rename=function(from,to)
 local label
 if to==root.."/retained.state" then label="retention_seal"
 elseif to==root.."/transaction.state" then label="journal_"..(state_phase(from) or "unknown")
 elseif to==root.."/previous.network" then label="previous_network"
 elseif to==root.."/previous.firewall" then label="previous_firewall"
 elseif to==root.."/candidate.network" then label="candidate_network"
 elseif to==root.."/candidate.firewall" then label="candidate_firewall"
 elseif to==root.."/previous.environment" then label="previous_environment"
 elseif to==root.."/previous.cache" then label="previous_cache"
 elseif to==root.."/candidate.environment" then label="candidate_environment"
 elseif to==root.."/candidate.cache" then label="candidate_cache"
 else
  for _,pkg in ipairs({"network","firewall","environment","cache"}) do
   if to==root.."/active/"..namespace.."_"..pkg then
    label=(state_phase(root.."/transaction.state")=="rolling_back" and "restore_" or "activate_")..pkg
   end
  end
 end
 if label==point and not fired and fault=="replace_fail" then fired=true;return false end
 if label==point and not fired and fault=="partial_scratch_crash" then
  fired=true;local fd=assert(n.open(from,n.open_flags("wronly","trunc")))
  assert(fd:writeall("partial_synthetic"));fd:close();os.exit(87)
 end
 local result=original_rename(from,to)
 if result and label==point and not fired then
  fired=true
  if fault=="crash" then os.exit(87)
  elseif fault=="pause" then
   io.write("AOTT_TRANSACTION_BARRIER:"..label.."\n");io.flush()
   assert(io.read("*l")=="continue","BARRIER_CANCELLED")
  end
 end
 return result
end
-- Fault injection is confined to the test fixture, never the core API.
local actual_open=n.open
local sync_fired=false
if fault=="sync_fail" then
 n.open=function(path,...)
  local fd=actual_open(path,...)
  if fd and (path==root.."/transaction.state.new" or path==root.."/retained.state.new" or path==root.."/active") then
   return {stat=function()return fd:stat()end,
    read=function(_,size)return fd:read(size)end,
    readall=function(_,size)return fd:readall(size)end,
    writeall=function(_,bytes)return fd:writeall(bytes)end,
    close=function()return fd:close()end,
    sync=function()
     local label=path==root.."/active" and "active_directory_sync" or
       (path==root.."/retained.state.new" and "retention_seal_sync" or
       ("journal_"..(state_phase(path) or "unknown").."_sync"))
     if label==point and not sync_fired then sync_fired=true;return false end
     return fd:sync()
    end}
  end
  return fd
 end
end
-- Boundary timing belongs only to this fixture. The transaction's own
-- monotonic/deadline logic stays unchanged and is still called normally.
local function deadline_clock(offset,advances)
 local raw=assert(fs.readfile(root.."/transaction.state",2048))
 local lines={};for value in raw:gmatch("([^\n]*)\n") do lines[#lines+1]=value end
 assert(((#lines==10 and lines[1]=="AOTT-C014-TXN-1")or (#lines==14 and (lines[1]=="AOTT-C014-TXN-2"or lines[1]=="AOTT-C014-TXN-3")))and lines[2]=="pending",
  "EXPECTED_PENDING_SYNTHETIC_JOURNAL")
 local deadline=assert(tonumber(lines[6]))
 local actual=n.sysinfo
 local baseline=actual().uptime
 n.sysinfo=function()
  local info=actual()
  -- Inject only the transaction deadline clock, never fabricate a live
  -- worker heartbeat or process-liveness clock in the admission module.
  local caller=debug.getinfo(2,"S")
  if caller and caller.source:match("/vlan_transaction%.lua$") then
   info.uptime=deadline+offset+(advances and (info.uptime-baseline) or 0)
  end
  return info
 end
end
if fs.lstat(root.."/native.environment") and fault~="native_missing_binding"then
 assert(dofile(repo.."/tests/c014_native_environment_fixture.lua").bind(root,vendor,fault))
end
if action=="lease_hold" then
 local lease=require "8311.environment_lease"
 local owner,why=lease.acquire(root,"offline_synthetic")
 if not owner then output(nil,why);return end
 if fault=="nested_lease"then
  local duplicate,e=lease.acquire(root,"offline_synthetic")
  eq(duplicate,nil,"nested_lease_refused");eq(e,"environment_lease_already_owned","same_process_lease")
  eq(lease.verify(owner),true,"original_lease_survives_nested_refusal")
 end
 if fault=="fork_lease_close"then
  local child=n.fork()
  if child==0 then
   local ok,e=lease.close(owner)
   eq(ok,nil,"child_cannot_close_parent_lease");eq(e,"environment_lease_process_changed","child_close_reason")
   os.exit(0)
  end
  local pid,kind,code=n.waitpid(child)
  eq(pid,child,"child_reaped");eq(code,0,"child_lease_test_passed")
  eq(lease.verify(owner),true,"lease_retained_after_child_exit")
 end
 io.write("AOTT_ENVIRONMENT_LEASE_READY\n");io.flush()
 assert(io.read("*l")=="continue","LEASE_TEST_RELEASE")
 local valid,e=lease.verify(owner);local closed=lease.close(owner)
 if not valid then output(nil,e);return end
 if not closed then output(nil,"environment_lease_release_unverified");return end
 output({status="SOURCE_ENVIRONMENT_LEASE_RELEASED"});return
elseif action=="boot_gate" then
 local gate=require "8311.boot_recovery_gate"
 local reads=0
 local evidence={disposable_fixture=true,root=root,read=function()
  reads=reads+1
  if fault=="source_exception" then error("PRIVATE_SOURCE_EXCEPTION",0)end
  local environment_path=root.."/active/"..namespace.."_environment"
  local cache_path=root.."/active/"..namespace.."_cache"
  local data
  if fs.lstat(environment_path)or fs.lstat(cache_path)then
   guard_file(environment_path);guard_file(cache_path)
   data=assert(require('8311.startup_state').evidence(fs.readfile(environment_path,4096),
       fs.readfile(cache_path,4096),snapshot(true,true).network))
  else
   local path=root.."/source-evidence.json";guard_file(path)
   data=assert(json.parse(assert(fs.readfile(path,8192))))
   data.network=snapshot(true,true).network
  end
  if fault=="saved_changes_after_review" and reads>=3 then
   data.environment.ipaddr={state="value",value="198.51.100.10"}
  elseif fault=="late_cache_conflict" and reads>=6 then
   data.cache.ipaddr={state="value",value="198.51.100.10"}
  elseif fault=="populate_matching_cache" and reads>=3 then
   for key,item in pairs(data.environment)do
    if key~="lct_vlan" and item.state=="value"then data.cache[key]={state="value",value=item.value}end
   end
  end
  return data
 end}
 local handle,why=gate.reconcile(root,"offline_synthetic",evidence)
 if not handle then output(nil,why);return end
 if fault=="consumer_write" then
  local code=native(root.."/active",{"set",packages.network..".lct.proto=dhcp"})
  eq(code,0,"consumer_native_write")
  code=native(root.."/active",{"commit",packages.network},true)
  eq(code,0,"consumer_native_commit")
  local delta=stage.."/delta/"..packages.network
  if fs.lstat(delta) then guard_file(delta);assert(fs.unlink(delta)) end
 end
 if fault=="boot_changed" then
  local realread=fs.readfile
  fs.readfile=function(path,...)
   if path=="/proc/sys/kernel/random/boot_id" then return "00000000-0000-0000-0000-000000000000\n" end
   return realread(path,...)
  end
 end
 if fault=="wrong_order" then output(gate.after(handle,"before_network","offline_synthetic"));return end
 local last
 for _,consumer in ipairs({"defaults_completed","sysinit_completed","before_network","netinit_completed","before_https"}) do
  local result,err=gate.after(handle,consumer,"offline_synthetic")
  if not result then output(nil,err);return end
  last=result
 end
 if fault=="repeat_final" then output(gate.after(handle,"before_https","offline_synthetic"));return end
 output(last);return
elseif action=="supervisor" then
 local supervisor=require "8311.recovery_supervisor"
 if fault=="worker_crash" then
  local gate=require "8311.recovery_admission"
  gate.step=function()os.exit(81)end
 elseif fault=="worker_hang" then
  local gate=require "8311.recovery_admission"
  local original=gate.step;local tick=0
  gate.step=function(...)
   tick=tick+1
   if tick>1 then while true do n.nanosleep(1,0)end end
   return original(...)
  end
 elseif fault=="nested_supervisor" then
  local fork=n.fork
  n.fork=function()
   local value,why=supervisor.run(root,ttl,"offline_synthetic")
   eq(value,nil,"no_recursive_supervision")
   eq(why,"supervisor_already_owned_in_process","nested_supervisor_reason")
   return fork()
  end
 end
 output(supervisor.run(root,ttl,"offline_synthetic"));return
elseif action=="supervisor_stop" then
 output(require('8311.recovery_supervisor').request_stop(root,"offline_synthetic"));return
elseif action=="admission_probe" then
 local gate=require "8311.recovery_admission"
 local proof,why=gate.present(root,"offline_synthetic")
 output(proof and {status="SOURCE_INDEPENDENT_WORKER_OBSERVED"} or nil,why);return
elseif action=="admission_self_hold" then
 local gate=require "8311.recovery_admission"
 local owner,why=gate.acquire(root,ttl,"offline_synthetic")
 if not owner then output(nil,why);return end
 assert(gate.pulse(owner,"offline_synthetic"))
 local proof,e=gate.present(root,"offline_synthetic")
 eq(proof,nil,"owner_cannot_attest_its_own_independence")
 eq(e,"recovery_worker_not_independent","self_refusal_reason")
 local second,e=gate.acquire(root,ttl,"offline_synthetic")
 eq(second,nil,"nested_owner_refused");eq(e,"recovery_worker_already_owned","nested_reason")
 io.write("AOTT_RECOVERY_ADMISSION_READY\n");io.flush()
 assert(io.read("*l")=="continue","SELF_HOLDER_RELEASE")
 output(gate.close(owner));return
elseif action=="admission_watch" then
 local gate=require "8311.recovery_admission"
 local owner,why=gate.acquire(root,ttl,"offline_synthetic")
 if not owner then output(nil,why);return end
 local first,e=gate.pulse(owner,"offline_synthetic")
 if not first then gate.close(owner);output(nil,e);return end
 io.write("AOTT_RECOVERY_ADMISSION_READY\n");io.flush()
 if fault=="freeze_before_ack" then
  assert(io.read("*l")=="continue","WORKER_BARRIER_CANCELLED")
 end
 while true do
  local result,err=gate.step(owner,"offline_synthetic")
  if not result then gate.close(owner);output(nil,err);return end
  if result.phase=="confirmed" or result.phase=="rolled_back" then
   gate.close(owner);output(result);return
  end
  if fault=="freeze_after_first_ack" and fs.lstat(root.."/recovery.ack") then
   io.write("AOTT_RECOVERY_ACK_FROZEN\n");io.flush()
   assert(io.read("*l")=="continue","ACK_FREEZE_RELEASE")
   fault="none"
  end
  n.nanosleep(0,100000000)
 end
elseif action=="watch" then
 io.write("AOTT_TRANSACTION_WATCH_READY\n");io.flush()
 if fault=="watch_after_pending" then
  assert(io.read("*l")=="continue","WATCH_BARRIER_CANCELLED")
  deadline_clock(0,true)
 end
 local until_time=n.sysinfo().uptime+15
 while n.sysinfo().uptime<until_time do
  local result,why=tx.recover(root,"offline_synthetic",true)
  if result and result.phase~="pending" then output(result);return end
  if not result and why~="transaction_not_armed" and why~="transaction_busy" and why~="environment_lease_busy" then output(nil,why);return end
  n.nanosleep(0,100000000)
 end
 output(nil,"synthetic_watch_deadline");return
elseif action=="preview" then
 output(tx.preview(root,"offline_synthetic"));return
elseif action=="recover" or action=="expire" then
 if fault=="changed_boot" then
  local readfile=fs.readfile
  fs.readfile=function(path,...)
   if path=="/proc/sys/kernel/random/boot_id" then return string.rep("f",8).."-"..string.rep("f",4).."-"..string.rep("f",4).."-"..string.rep("f",4).."-"..string.rep("f",12).."\n" end
   return readfile(path,...)
  end
 elseif fault=="backward_clock" then
  local sysinfo=n.sysinfo;n.sysinfo=function()local t=sysinfo();t.uptime=0;return t end
 end
 output(tx.recover(root,"offline_synthetic",action=="expire"));return
elseif action=="confirm" then
 if fault=="clock_before_deadline" then deadline_clock(-1,false)
 elseif fault=="clock_at_deadline" then deadline_clock(0,false)
 elseif fault=="clock_after_deadline" then deadline_clock(1,false) end
 local health={disposable_fixture=true,transaction_directory=root,operator_confirmed=true,
 inspect=function(id)
  if fault=="health_exception" then error("SYNTHETIC_PRIVATE_HEALTH",0) end
  if fault=="deadline_during_probe" then
   local real_clock=n.sysinfo;n.sysinfo=function()
    local t=real_clock();local caller=debug.getinfo(2,"S")
    if caller and caller.source:match("/vlan_transaction%.lua$") then t.uptime=t.uptime+1000 end
    return t
   end
  end
  return {transaction_id=id,synthetic_only=true,management_reachable=fault~="management_failed",
   forwarding_healthy=fault~="forwarding_failed",recovery_ready=fault~="recovery_failed"}
 end}
 if fault=="no_consent" then health.operator_confirmed=false end
 output(tx.confirm(root,supplied_id,health,"offline_synthetic"));return
end
local preview,why=tx.preview(root,"offline_synthetic")
if not preview then output(nil,why);return end
if fault=="activation_failed" then adapter.activation_ready=function()return false end
elseif fault=="activation_exception" then adapter.activation_ready=function()error("SYNTHETIC_PRIVATE_ACTIVATION",0)end
elseif fault=="bad_active_readback" then
 adapter.applied_readback=function()local t=snapshot(true,true);t.network.lct.options.proto="INVALID";return t end
elseif fault=="nested_call" then
 adapter.activation_ready=function()
  local result,e=tx.recover(root,"offline_synthetic")
  eq(result,nil,"nested_result");eq(e,"transaction_already_owned_in_process","nested_lock_preserved")
  return true
 end
end
local req={operator_confirmed=fault~="no_consent",review_revision=preview.review_revision,
 ttl_seconds=ttl,vlan=123,parent="eth0_0_1_lct",zone="lan",scope=preview.scope}
if fault=="omit_source_scope"then req.scope=nil end
if fault=="wrong_source_scope"then req.scope="uci_only"end
if fault=="vlan_unchanged"then req.vlan=0 end
if fault=="stale_preview" then req.review_revision=string.rep("0",128) end
if fault=="wrong_adapter" then adapter.transaction_directory=stage end
if fault=="invalid_vlan" then req.vlan=4095 end
output(tx.begin(root,stage,adapter,req,"offline_synthetic"))
