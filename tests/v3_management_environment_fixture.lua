local root=assert(arg[1],"overlay lua root required")
package.path=root.."/?.lua;"..package.path

local function ip(a,b,c,d) return table.concat({a,b,c,d},".") end
local function mac(a,b,c,d,e,f) return table.concat({a,b,c,d,e,f},":") end

local state={
 ipaddr={state="value",value=ip('192','0','2','1')},
 netmask={state="value",value=ip('255','255','255','0')},
 gateway={state="unset"},
 dns_server={state="value",value=ip('192','0','2','53')},
 lct_mac={state="value",value=mac('02','11','22','33','44','55')},
 lct_vlan={state="value",value="0"},
}
local fail_key=nil
local function clone(t)
 local r={};for k,v in pairs(t) do
  if type(v)=="table" then r[k]=clone(v) else r[k]=v end
 end;return r
end
package.preload["8311.native_management_reader"]=function()
 return {
  read=function() return {} end,
  records=function() return clone(state) end,
 }
end
package.preload["8311.tools"]=function()
 return {
  fw_setenv_8311=function(args)
   local key,value=args[1],args[2]
   if key==fail_key then fail_key=nil;return false end
   if value==nil or value=="" then state[key]={state="unset"}
   else state[key]={state="value",value=value} end
   return true
  end
 }
end

local env=require "8311.management_environment"
local checks=0
local function eq(a,b,label)
 checks=checks+1
 assert(a==b,"MANAGEMENT_ENV_FIXTURE:"..label..
        " expected="..tostring(b).." got="..tostring(a))
end

local raw,records=assert(env.snapshot())
eq(raw:match("^AOTT%-MANAGEMENT%-ENV%-1")~=nil,true,"header")
eq(records.ipaddr.value,ip('192','0','2','1'),"snapshot_ip")
local decoded=assert(env.decode(raw))
eq(decoded.gateway.state,"unset","gateway_unset")
eq(decoded.dns_server.value,ip('192','0','2','53'),"dns_value")

local desired=assert(env.request(raw,{
 ipaddr=ip('198','51','100','10'),netmask=ip('255','255','255','0'),
 gateway=ip('198','51','100','1'),dns_server=ip('198','51','100','53'),
 lct_mac=mac('02','AA','BB','CC','DD','EE'),vlan=123,
}))
local d=assert(env.decode(desired))
eq(d.ipaddr.value,ip('198','51','100','10'),"request_ip")
eq(d.lct_vlan.value,"123","request_vlan")
eq(d.lct_mac.value,mac('02','AA','BB','CC','DD','EE'),"request_mac")

local receipt,applied=assert(env.apply_request(raw,{
 ipaddr=ip('198','51','100','10'),netmask=ip('255','255','255','0'),
 gateway="",dns_server="",
 lct_mac=mac('02','AA','BB','CC','DD','EE'),vlan=123,
}))
eq(receipt.status,"MANAGEMENT_ENVIRONMENT_APPLIED","apply_status")
eq(state.ipaddr.value,ip('198','51','100','10'),"applied_ip")
eq(state.gateway.state,"unset","applied_gateway_deleted")
eq(state.dns_server.state,"unset","applied_dns_deleted")
eq(state.lct_vlan.value,"123","applied_vlan")
eq(applied,assert(env.snapshot()),"apply_readback_bytes")

local restored=assert(env.restore(raw))
eq(restored.status,"MANAGEMENT_ENVIRONMENT_RESTORED","restore_status")
eq(state.ipaddr.value,ip('192','0','2','1'),"restored_ip")
eq(state.gateway.state,"unset","restored_gateway")
eq(state.dns_server.value,ip('192','0','2','53'),"restored_dns")
eq(state.lct_vlan.value,"0","restored_vlan")

-- Failed request write triggers best-effort restore of the complete prior state.
fail_key="dns_server"
local bad,why=env.apply_request(raw,{
 ipaddr=ip('203','0','113','9'),netmask=ip('255','255','255','0'),
 gateway=ip('203','0','113','1'),dns_server=ip('203','0','113','53'),
 lct_mac=mac('02','10','20','30','40','50'),vlan=44,
})
eq(bad,nil,"failure_returns_nil")
eq(why,"management_environment_apply_write_failed","failure_reason")
eq(assert(env.snapshot()),raw,"failure_restored_exact_snapshot")

-- Present-empty is deliberately unqualified because empty fwenv means delete.
local empty=clone(state)
empty.gateway={state="value",value=""}
local encoded,ewhy=env.encode(empty)
eq(encoded,nil,"present_empty_refused")
eq(ewhy,"management_environment_snapshot_invalid","present_empty_reason")

local invalid,invalidwhy=env.request(raw,{
 ipaddr=ip('198','51','100','10'),netmask=ip('255','255','255','0'),
 gateway="",dns_server="",lct_mac="",vlan=0,
})
eq(invalid,nil,"incomplete_request_refused")
eq(invalidwhy,"management_environment_request_incomplete","incomplete_reason")

eq(checks>=25,true,"coverage")
print("AOTT_V3_MANAGEMENT_ENVIRONMENT_PASS checks="..checks)
