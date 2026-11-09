local root=assert(arg[1],"overlay lua root required")
package.path=root.."/?.lua;"..package.path

local function ip(a,b,c,d) return table.concat({a,b,c,d},".") end
local function mac(a,b,c,d,e,f) return table.concat({a,b,c,d,e,f},":") end
package.preload["nixio.fs"]=function() return {readfile=function() return nil end} end
package.preload["luci.jsonc"]=function() return {parse=function() return nil end} end
package.preload["8311.webutil"]=function() return {capture=function() return 1,"",false end} end

local M=require "8311.management_runtime"

local request={
    vlan=0,ipaddr=ip('192','0','2','10'),netmask=ip('255','255','255','0'),
    gateway=ip('192','0','2','1'),dns_server=ip('192','0','2','53'),
    lct_mac=mac('02','00','00','00','00','10')
}
local status={
    up=true,l3_device="eth0_0_1_lct",device="eth0_0_1_lct",
    ["ipv4-address"]={{address=ip('192','0','2','10'),mask=24}},
    route={{target=ip('0','0','0','0'),mask=0,nexthop=ip('192','0','2','1')}},
    ["dns-server"]={ip('192','0','2','53')}
}
local receipt=assert(M.verify(request,status,mac('02','00','00','00','00','10')))
assert(receipt.status=="MANAGEMENT_RUNTIME_CONVERGED")
assert(receipt.management_section=="lct")
assert(receipt.ipv4_verified and receipt.netmask_verified and
       receipt.gateway_verified and receipt.dns_verified and
       receipt.mac_verified and receipt.vlan_mode_verified)
assert(receipt.contains_configuration_values==false)
for k,v in pairs(receipt) do
    assert(v~=ip('192','0','2','10') and v~=ip('192','0','2','1') and v~=ip('192','0','2','53') and
           v~=mac('02','00','00','00','00','10'),"receipt leaked configured value")
end

local tagged={
    vlan=321,ipaddr=ip('198','51','100','10'),netmask=ip('255','255','255','0'),
    gateway="",dns_server="",lct_mac=mac('02','00','00','00','00','20')
}
local tagged_status={
    up=true,l3_device="mgmt",device="mgmt",
    ["ipv4-address"]={{address=ip('198','51','100','10'),mask=24}},
    route={},
    ["dns-server"]={}
}
local tagged_receipt=assert(M.verify(tagged,tagged_status,mac('02','00','00','00','00','20'),"2: mgmt@eth0_0_1_lct: <UP> mtu 1500\n    vlan protocol 802.1Q id 321 <REORDER_HDR>"))
assert(tagged_receipt.management_section=="mgmt")
assert(tagged_receipt.vlan_id_verified==true)

local wrong_vlan,wrong_why=M.verify(tagged,tagged_status,
    mac('02','00','00','00','00','20'),
    "2: mgmt@eth0_0_1_lct: <UP> mtu 1500\n    vlan protocol 802.1Q id 322 <REORDER_HDR>")
assert(wrong_vlan==nil and wrong_why=="management_runtime_vlan_id_mismatch")

local bad_dns={
    up=true,l3_device="eth0_0_1_lct",device="eth0_0_1_lct",
    ["ipv4-address"]={{address=ip('192','0','2','10'),mask=24}},
    route={{target=ip('0','0','0','0'),mask=0,nexthop=ip('192','0','2','1')}},
    ["dns-server"]={ip('192','0','2','54')}
}
local nope,why=M.verify(request,bad_dns,mac('02','00','00','00','00','10'))
assert(nope==nil and why=="management_runtime_state_mismatch")

local ambiguous={
    up=true,l3_device="eth0_0_1_lct",device="eth0_0_1_lct",
    ["ipv4-address"]={{address=ip('192','0','2','10'),mask=24}},
    route={
      {target=ip('0','0','0','0'),mask=0,nexthop=ip('192','0','2','1')},
      {target=ip('0','0','0','0'),mask=0,nexthop=ip('192','0','2','2')}
    },
    ["dns-server"]={ip('192','0','2','53')}
}
nope,why=M.verify(request,ambiguous,mac('02','00','00','00','00','10'))
assert(nope==nil and why=="management_default_route_ambiguous")

local invalid={}
for k,v in pairs(request) do invalid[k]=v end
invalid.extra="refused"
nope,why=M.verify(invalid,status,mac('02','00','00','00','00','10'))
assert(nope==nil and why=="management_runtime_request_invalid")

print("AOTT_V3_MANAGEMENT_RUNTIME_PASS")
