local root=assert(arg[1],"overlay lua root required")
package.path=root.."/?.lua;"..package.path

local function dotted(parts) return table.concat(parts,".") end
local mac=table.concat({"02","00","00","00","00","01"},":")
local ip=dotted({"192","0","2","10"})
local mask=dotted({"255","255","255","0"})
local gateway=dotted({"192","0","2","1"})
local dns=dotted({"192","0","2","53"})
local network=table.concat({
"package network",
"config interface 'lct'",
" option ifname 'eth0_0_1_lct'",
" option proto 'static'",
" option ipaddr '"..ip.."'",
" option netmask '"..mask.."'",
" option gateway '"..gateway.."'",
" option dns '"..dns.."'",
" option macaddr '"..mac.."'",
""
},"\n")
local firewall=table.concat({
"package firewall",
"config zone",
" option name 'lan'",
" list network 'lan'",
" list network 'lct'",
""
},"\n")
local native=table.concat({
"8311_ipaddr="..ip,
"8311_netmask="..mask,
"8311_gateway="..gateway,
"8311_dns_server="..dns,
"8311_lct_mac="..mac,
"8311_lct_vlan=0",
""
},"\n")

package.preload["nixio.fs"]=function()
 return {
  readfile=function(path)
   if path=="/proc/mounts" then
    return "ubi0:ptconf /ptconf ubifs rw,sync,relatime 0 0\n"
   end
  end,
  lstat=function(path)
   if path=="/ptconf" or path=="/ptconf/8311" then
    return {type="dir",uid=0,gid=0,modedec=493,dev=9}
   end
   return nil
  end,
  statvfs=function(path)
   assert(path=="/ptconf")
   return {frsize=4096,bavail=1024,flag=0,files=0,favail=0}
  end
 }
end
package.preload["8311.webutil"]=function()
 return {
  capture=function(argv,maximum)
   local joined=table.concat(argv," ")
   if joined:find("/usr/sbin/fw_printenv",1,true) then
    assert(maximum==4096);return 0,native,false
   end
   if joined:find("/sbin/uci export network",1,true) then
    return 0,network,false
   end
   if joined:find("/sbin/uci export firewall",1,true) then
    return 0,firewall,false
   end
   error("unexpected command")
  end
 }
end

local m=require "8311.management_preflight"
local s=m.status()
assert(s.schema==1 and s.preview_available==true)
assert(s.storage.fs_type=="ubifs")
assert(s.storage.capacity_qualified==true)
assert(s.storage.store_present==false)
assert(s.storage.provisioning_required==true)
assert(s.native.fields==6 and s.native.present==6 and s.native.present_empty==0)
assert(s.topology.current_vlan==0)
assert(s.production_write_allowed==false)
local p=assert(m.preview("123"))
assert(p.current_vlan==0 and p.requested_vlan==123)
assert(p.operations>0 and p.network_operations>0)
assert(p.recovery_provisioning_required==true)
assert(p.production_write_allowed==false)
assert(p.contains_configuration_values==false)
assert(p.uci_write_performed==false)
assert(p.native_environment_write_performed==false)
local same=assert(m.preview("0"))
assert(same.changes_required==false and same.operations==0)
local bad,why=m.preview("4095")
assert(bad==nil and why=="Management VLAN must be 0 through 4094")
print("AOTT_V3_MANAGEMENT_PREFLIGHT_PASS")
