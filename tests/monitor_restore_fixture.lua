-- Isolated boot restore with exact allowlisted UCI keys and no live target.
local module_path=assert(arg[1])
local good={
 schema=1,log_remote="1",log_ip="collector.example.com",
 log_port="5514",log_proto="udp",aott_metrics="1",
 aott_metrics_client="192" .. ".0.2.40",
 aott_metrics_sha256=string.rep("a",64)
}
local valid=true
local record_present=true
local state={hostname="generic-test"}
local calls={}
package.preload["8311.monitor_store"]=function()
 return {
  read=function()return record_present and good or nil end,
  valid=function(record)return valid and record==good end
 }
end
package.preload["8311.webutil"]=function()return {capture=function() error("Unexpected raw capture")end}end
local mod=assert(loadfile(module_path))()
local function run(argv)
 local command=argv[7]
 local value=argv[8]
 assert(argv[1]=="/usr/bin/timeout" and argv[2]=="-k")
 assert(argv[5]=="/sbin/uci" and argv[6]=="-q")
 calls[#calls+1]=command..":"..(value or "")
 if command=="get" then
  if value=="system.@system[0]" then return "system" end
  local field=value:match("^system%.@system%[0%]%.([a-z0-9_]+)$")
  assert(field)
  return state[field]
 elseif command=="set" then
  local field,v=value:match("^system%.@system%[0%]%.([a-z0-9_]+)=(.*)$")
  assert(field and field~="hostname")
  state[field]=v
  return ""
 elseif command=="commit" then
  assert(value=="system")
  return ""
 end
 error("Unexpected restore command")
end
local ok,result=mod.run(run)
assert(ok and result=="restored")
assert(state.hostname=="generic-test")
for k,v in pairs(good) do
 if k~="schema" then assert(state[k]==v, "Missing restored "..k) end
end
assert(#calls>=1)
calls={}
ok,result=mod.run(run)
assert(ok and result=="already-current")
for _,item in ipairs(calls)do
 assert(not item:match("^set:") and not item:match("^commit:"))
end
record_present=false;calls={}
ok,result=mod.run(run)
assert(not ok and result=="Persistent monitoring configuration unavailable")
assert(#calls==0)
record_present=true;valid=false;calls={}
ok,result=mod.run(run)
assert(not ok and result=="Persistent monitoring record is invalid")
assert(#calls==0)
print("BOOTS_RESTORE_ISOLATED_PASS")
