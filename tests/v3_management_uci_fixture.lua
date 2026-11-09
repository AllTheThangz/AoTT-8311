local root=assert(arg[1],"overlay lua root required")
package.path=root.."/?.lua;"..package.path

local function ip(a,b,c,d) return table.concat({a,b,c,d},".") end
local function mac(a,b,c,d,e,f) return table.concat({a,b,c,d,e,f},":") end

local state={
 network={
  lct={type="interface",options={
   ifname="eth0_0_1_lct",proto="static",auto="1",
   macaddr=mac('02','11','22','33','44','55'),
   ipaddr=ip('192','0','2','1'),netmask=ip('255','255','255','0'),
   gateway=ip('192','0','2','254'),dns=ip('192','0','2','53'),
  }},
 },
 firewall={
  ["@zone[0]"]={type="zone",options={
   name="lan",network={"lan","lct"},input="ACCEPT",
   output="ACCEPT",forward="ACCEPT",
  }},
 },
}
local function copy(t)
 if type(t)~="table" then return t end
 local r={};for k,v in pairs(t)do r[k]=copy(v)end;return r
end
local backup=copy(state)
local function quote(v)
 return "'"..tostring(v):gsub("'","'\\''").."'"
end
local function export_state(source,pkg)
 local out={"package "..pkg}
 local names={}
 for name in pairs(source[pkg])do names[#names+1]=name end
 table.sort(names)
 for _,name in ipairs(names)do
  local sec=source[pkg][name]
  if name:sub(1,1)=="@" then
   out[#out+1]="config "..sec.type
  else
   out[#out+1]="config "..sec.type.." "..quote(name)
  end
  local keys={}
  for key in pairs(sec.options)do keys[#keys+1]=key end
  table.sort(keys)
  for _,key in ipairs(keys)do
   local value=sec.options[key]
   if type(value)=="table" then
    for _,item in ipairs(value)do
     out[#out+1]="list "..key.." "..quote(item)
    end
   else
    out[#out+1]="option "..key.." "..quote(value)
   end
  end
 end
 return table.concat(out,"\n").."\n"
end
local function export(pkg)return export_state(state,pkg)end

local NETWORK="/ptconf/8311/aott-recovery/v1/management/network.before"
local FIREWALL="/ptconf/8311/aott-recovery/v1/management/firewall.before"
package.preload["nixio.fs"]=function()
 return {
  lstat=function(path)
   local pkg=path==NETWORK and "network" or path==FIREWALL and "firewall" or nil
   if not pkg then return nil end
   local raw=export_state(backup,pkg)
   return {type="reg",uid=0,gid=0,modedec=600,nlink=1,size=#raw}
  end,
  readfile=function(path,limit)
   local pkg=path==NETWORK and "network" or path==FIREWALL and "firewall" or nil
   if not pkg then return nil end
   local raw=export_state(backup,pkg)
   return limit and raw:sub(1,limit) or raw
  end,
 }
end

local captures={}
package.preload["8311.webutil"]=function()
 return {
  capture=function(argv,limit)
   captures[#captures+1]=copy(argv)
   if argv[1]=="/sbin/uci" and argv[2]=="export" then
    local raw=export(argv[3])
    return 0,raw,false
   end
   if argv[1]=="/sbin/uci" and argv[2]=="-f" and argv[4]=="import" then
    local pkg=argv[5]
    if (pkg=="network" and argv[3]==NETWORK) or
       (pkg=="firewall" and argv[3]==FIREWALL) then
      state[pkg]=copy(backup[pkg])
      return 0,"",false
    end
    return 64,"",false
   end
   if argv[1]=="/sbin/uci" and argv[2]=="commit" then
    return 0,"",false
   end
   return 64,"",false
  end
 }
end

local function cursor()
 local C={}
 function C:set(pkg,section,a,b)
  local sec=state[pkg][section]
  if b==nil then
   if not sec then state[pkg][section]={type=a,options={}};return true end
   sec.type=a;return true
  end
  if not sec then return false end
  sec.options[a]=b
  return true
 end
 function C:delete(pkg,section,option)
  local sec=state[pkg][section]
  if not sec then return true end
  if option then sec.options[option]=nil else state[pkg][section]=nil end
  return true
 end
 function C:add_list(pkg,section,option,value)
  local sec=state[pkg][section];if not sec then return false end
  local list=sec.options[option]
  if list==nil then list={}
  elseif type(list)~="table" then return false end
  list[#list+1]=value;sec.options[option]=list
  return true
 end
 function C:commit(pkg)
  return pkg=="network" or pkg=="firewall"
 end
 return C
end
package.preload["luci.model.uci"]=function()return{cursor=cursor}end

local transition=require"8311.vlan_transition"
local management=require"8311.management_uci"

local checks=0
local function eq(a,b,label)
 checks=checks+1
 assert(a==b,"MANAGEMENT_UCI_FIXTURE:"..label..
  " expected="..tostring(b).." got="..tostring(a))
end

local snap,raw=assert(management.snapshot())
eq(type(raw.network),"string","raw_network")
eq(type(raw.firewall),"string","raw_firewall")
eq(snap.network.lct.options.ipaddr,ip('192','0','2','1'),"initial_ip")

local handle=assert(transition.prepare_management(snap,{
 vlan=123,ipaddr=ip('198','51','100','10'),netmask=ip('255','255','255','0'),
 gateway=ip('198','51','100','1'),dns_server=ip('198','51','100','53'),
 lct_mac=mac('02','AA','BB','CC','DD','EE'),
},"eth0_0_1_lct","lan"))
local receipt,why=management.apply(handle)
assert(receipt,why)
eq(receipt.status,"MANAGEMENT_UCI_APPLIED_VERIFIED","apply_status")
eq(receipt.production_applied,true,"production")
eq(receipt.contains_configuration_values,false,"redacted")
eq(state.network.mgmt.options.ipaddr,ip('198','51','100','10'),"applied_ip")
eq(state.network.mgmt.options.dns,ip('198','51','100','53'),"applied_dns")
eq(state.network.mgmt.options.macaddr,mac('02','AA','BB','CC','DD','EE'),"applied_mac")
eq(state.network.lct_vlan.options.vid,"123","applied_vlan")

local adapter=management.adapter()
eq(adapter.command({"set","evil.section=value"}),false,"package_refused")
eq(adapter.command({"exec","network.lct.ipaddr="..ip("192","0","2","1")}),false,"verb_refused")

local ok,err=management.import_raw("network","/tmp/network")
eq(ok,nil,"restore_path_refused")
eq(err,"management_uci_restore_scope_refused","restore_path_reason")
assert(management.import_raw("network",NETWORK))
eq(state.network.lct.options.ipaddr,ip('192','0','2','1'),"restored_ip")
eq(state.network.mgmt,nil,"restored_removed_mgmt")
eq(state.network.lct_vlan,nil,"restored_removed_vlan")

local saw_import,saw_commit,saw_export=false,false,false
for _,argv in ipairs(captures)do
 if argv[1]=="/sbin/uci" and argv[2]=="-f" and argv[4]=="import" and argv[5]=="network" then
  saw_import=true
 elseif argv[1]=="/sbin/uci" and argv[2]=="commit" and argv[3]=="network" then
  saw_commit=true
 elseif argv[1]=="/sbin/uci" and argv[2]=="export" and argv[3]=="network" then
  saw_export=true
 end
end
eq(saw_import,true,"restore_import_invoked")
eq(saw_commit,true,"restore_commit_invoked")
eq(saw_export,true,"restore_readback_export_invoked")

eq(checks>=18,true,"coverage")
print("AOTT_V3_MANAGEMENT_UCI_PASS checks="..checks)
