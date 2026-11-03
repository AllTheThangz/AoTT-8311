-- H-023 cross-process lifecycle ownership, offline extracted vendor MIPS.
-- No actual PON/ethtool execution; native provider is fully synthetic.
local root=assert(arg[1])
local library=assert(arg[2])
local overlay=assert(arg[3])
local mode=assert(arg[4])
local directory=assert(arg[5])
package.path=library.."/?.lua;"..overlay.."/?.lua;"..
  root.."/usr/lib/lua/?.lua;"..root.."/usr/lib/lua/?/init.lua;"..
  package.path
package.cpath=root.."/usr/lib/lua/?.so;"..package.cpath

local preferences=require "8311.history_preferences"
local lifecycle=require "8311.history_lifecycle"
local caps={kind="source_only",native_qualified=true}
local p=assert(preferences.simulate(preferences.defaults(),{
  sampling_enabled=true,pon_interval_seconds=60,
  host_interval_seconds=120,
},1,caps))
local session=assert(lifecycle.new(directory,p,caps,"offline_synthetic"))
local ready,why=lifecycle.start(session,100)
if mode=="try" and ready and ready.status=="owner_busy" then
  assert(ready.owns_kernel_lock==false)
  assert(ready.next_start_uptime==160)
  assert(ready.lifetime_starts==0)
  assert(ready.failed_start_count==1)
  print("AOTT_H023_BUSY")
  return
end
assert(ready and ready.status=="running",why or "start_not_running")
assert(assert(lifecycle.status(session)).owns_kernel_lock)
local provider={uptime=100,reads=0,commands=0}
local boot="11111111-2222-4333-8444-555555555555"
function provider.read(path,maximum)
  provider.reads=provider.reads+1
  if path=="/proc/sys/kernel/random/boot_id" then
    assert(maximum==80)
    return boot.."\n"
  elseif path=="/proc/uptime" then
    assert(maximum==80)
    return tostring(provider.uptime).." 17.0\n"
  elseif path=="/sys/class/net/eth0_0/speed" then
    assert(maximum==32)
    return "10000\n"
  end
  error("Unexpected source kernel path")
end
function provider.run(argv,maximum)
  provider.commands=provider.commands+1
  local value=table.concat(argv," ")
  if value=="/usr/bin/timeout -k 1 3 /usr/bin/pon psg" then
    assert(maximum==1024)
    return 0,"current=51\n",false
  elseif value=="/usr/bin/timeout -k 1 4 /usr/sbin/ethtool -S eth0_0" then
    assert(maximum==16384)
    local rate=math.floor(provider.uptime*1250000)
    return 0,"RxGoodBytes: "..tostring(rate)..
      "\nTxGoodBytes: "..tostring(rate*2).."\n",false
  end
  error("Unexpected source process")
end
assert(lifecycle.step(session,100,provider).status=="sample_accepted")
provider.uptime=160
local x=assert(lifecycle.step(session,160,provider))
assert(x.due_pon==true and x.due_host==false)
provider.uptime=220
assert(lifecycle.step(session,220,provider).has_rate==true)
assert(provider.commands==5)
local document=assert(lifecycle.export_json(session,"hour"))
assert(document:find('"not_sampled"',1,true))
assert(not document:find(boot,1,true))
print("AOTT_H023_RUNNING")
io.stdout:flush()
if mode=="hold" or mode=="hold_exit" then io.read("*l") end
if mode=="hold_exit" then
  print("AOTT_H023_EXIT_WITHOUT_CLOSE")
  os.exit(0)
end
assert(lifecycle.shutdown(session).phase=="closed")
print("AOTT_H023_CLOSED")
