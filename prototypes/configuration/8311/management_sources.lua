-- Management source-precedence agreement. Pure Lua 5.1, no environment writes.
-- Stored overrides, current-boot caches, board fallback and intended UCI are
-- distinct evidence. Agreement is not proof of a future reboot or live service.
local M={}
local PRIVATE=setmetatable({}, {__mode='k'})
local ERROR={}
local FIELDS={'ipaddr','netmask','gateway','dns_server','lct_mac','lct_vlan'}
local CACHED={ipaddr=true,netmask=true,gateway=true,dns_server=true,lct_mac=true}
local function fail(code)error({tag=ERROR,code=code},0)end
local function safe(fn,...)
 local ok,v=pcall(fn,...)
 if ok then return v end
 if type(v)=='table' and rawget(v,'tag')==ERROR then return nil,rawget(v,'code') end
 return nil,'management_sources_internal_error'
end
local function plain(v)return type(v)=='table' and getmetatable(v)==nil end
local function text(v)return type(v)=='string' and #v<=128 and not v:find('[%z\1-\31\127]')end
local function copy(v)
 if type(v)~='table' then return v end
 local out={};for k,x in pairs(v)do out[k]=copy(x)end;return out
end
local function equal(a,b)
 if type(a)~=type(b)then return false end
 if type(a)~='table'then return a==b end
 for k,v in pairs(a)do if not equal(v,b[k])then return false end end
 for k in pairs(b)do if a[k]==nil then return false end end
 return true
end
local function ipv4(v)
 if not text(v)then return nil end
 local a,b,c,d=v:match('^(%d+)%.(%d+)%.(%d+)%.(%d+)$')
 if not a then return nil end
 local n=0
 for _,x in ipairs({a,b,c,d})do
  if #x>3 or (#x>1 and x:sub(1,1)=='0')or tonumber(x)>255 then return nil end
  n=n*256+tonumber(x)
 end
 return n
end
local function value(id,v,optional)
 if not text(v)then fail('management_value_unqualified_'..id)end
 if id=='lct_vlan'then
  if not v:match('^%d+$')or #v>4 or tonumber(v)>4094 or tostring(tonumber(v))~=v then
   fail('management_value_unqualified_lct_vlan')end
  return v
 elseif id=='lct_mac'then
  if not v:match('^%x%x:%x%x:%x%x:%x%x:%x%x:%x%x$')then fail('management_value_unqualified_lct_mac')end
  return v:lower()
 elseif (id=='gateway'or id=='dns_server')and optional and v==''then return '' end
 local n=ipv4(v)
 if not n then fail('management_value_unqualified_'..id)end
 if id=='netmask'then
  local valid=false
  for bits=0,32 do if n==4294967296-2^(32-bits)then valid=true;break end end
  if not valid then fail('management_value_unqualified_netmask')end
 end
 return v
end
local function record(v,missing)
 if not plain(v)or type(v.state)~='string'then fail('management_evidence_record_invalid')end
 for k in pairs(v)do if k~='state'and k~='value'then fail('management_evidence_record_invalid')end end
 if v.state=='unreadable'then fail('management_evidence_unavailable')end
 if v.state==missing then
  if v.value~=nil then fail('management_evidence_record_invalid')end
  return nil
 end
 if v.state~='value'or not text(v.value)then fail('management_evidence_record_invalid')end
 return v.value
end
local function managed_profile(net)
 if not plain(net)then fail('management_uci_unqualified')end
 local function section(name,kind)
  local s=net[name]
  if not plain(s)or s.type~=kind or not plain(s.options)then fail('management_uci_unqualified')end
  return s.options
 end
 local lct=section('lct','interface')
 if lct.ifname~='eth0_0_1_lct'or lct.proto~='static'then fail('management_parent_unqualified')end
 local opts=lct;local vlan='0'
 if net.mgmt~=nil or net.lct_vlan~=nil then
  local mgmt=section('mgmt','interface');local dev=section('lct_vlan','device')
  if mgmt.ifname~='mgmt'or mgmt.proto~='static'or dev.type~='8021q'or dev.name~='mgmt'or
     dev.ifname~=lct.ifname or lct.ipaddr~=nil or lct.netmask~=nil or lct.gateway~=nil or lct.dns~=nil then
   fail('management_uci_topology_ambiguous')end
  vlan=value('lct_vlan',dev.vid)
  if vlan=='0'then fail('management_uci_topology_ambiguous')end
  if value('lct_mac',mgmt.macaddr)~=value('lct_mac',lct.macaddr)then fail('management_uci_mac_ambiguous')end
  opts=mgmt
 end
 local dns=opts.dns or ''
 if type(dns)=='table'then
  if not plain(dns)or type(dns[1])~='string'then fail('management_dns_unqualified')end
  for k in pairs(dns)do if k~=1 then fail('management_dns_unqualified')end end
  dns=dns[1]
 end
 return {ipaddr=value('ipaddr',opts.ipaddr),netmask=value('netmask',opts.netmask),
  gateway=value('gateway',opts.gateway or '',true),dns_server=value('dns_server',dns,true),
  lct_mac=value('lct_mac',opts.macaddr),lct_vlan=vlan}
end
local function inspect(data)
 if not plain(data)or not plain(data.environment)or not plain(data.cache)then fail('management_evidence_invalid')end
 for k in pairs(data)do
  if k~='environment'and k~='cache'and k~='factory_mac'and k~='network'then fail('management_evidence_invalid')end
 end
 local allowed={};for _,id in ipairs(FIELDS)do allowed[id]=true end
 for k in pairs(data.environment)do if not allowed[k]then fail('management_environment_scope_invalid')end end
 for k in pairs(data.cache)do if not CACHED[k]then fail('management_cache_scope_invalid')end end
 local saved={}
 local raw={environment={},cache={},factory_mac=nil}
 local fallback=nil
 -- Factory fallback may be unavailable without disqualifying an explicit MAC.
 if data.factory_mac~=nil then
  if not plain(data.factory_mac)then fail('management_fallback_invalid')end
  for k in pairs(data.factory_mac)do if k~='state'and k~='value'then fail('management_fallback_invalid')end end
 end
 local count=0
 for _,id in ipairs(FIELDS)do
  local v=record(data.environment[id],'unset');raw.environment[id]=copy(data.environment[id])
  if v==nil or v==''then
   if id=='ipaddr'then v='192.168.11.1'
   elseif id=='netmask'then v='255.255.255.0'
   elseif id=='lct_vlan'then v='0'
   elseif id=='lct_mac'then
    fallback=record(data.factory_mac,'absent')
    if not fallback then fail('management_factory_mac_unavailable')end
    raw.factory_mac=copy(data.factory_mac);v=fallback
   else v=''end
  end
  saved[id]=value(id,v,true)
 end
 local current={}
 for _,id in ipairs(FIELDS)do
  if CACHED[id]then
   local cached=record(data.cache[id],'absent');raw.cache[id]=copy(data.cache[id])
   if cached~=nil then count=count+1;current[id]=value(id,cached,true)
   else current[id]=saved[id]end
  else current[id]=saved[id]end
  if current[id]~=saved[id]then fail('startup_cache_conflicts_'..id)end
 end
 local configured=managed_profile(data.network)
 for _,id in ipairs(FIELDS)do
  if configured[id]~=saved[id]then fail('startup_override_conflicts_'..id)end
 end
 -- Only bounded validated evidence is retained. Never hold a full raw boot
 -- environment or arbitrary nested adapter object in the private proof.
 return {saved=saved,current=current,configured=configured,raw=raw,cache_count=count}
end
function M.review(data)
 return safe(function()
  local result=inspect(data);local h={};PRIVATE[h]=result;return h
 end)
end
function M.verify(h,data)
 return safe(function()
  local old=type(h)=='table'and PRIVATE[h]
  if not old then fail('invalid_management_source_proof')end
  local new=inspect(data)
  if not equal(old.saved,new.saved)or not equal(old.configured,new.configured)or
     not equal(old.raw.environment,new.raw.environment)or not equal(old.raw.factory_mac,new.raw.factory_mac)then
   fail('management_sources_changed')end
  for id in pairs(CACHED)do
   -- Defaults may legitimately populate a previously absent cache with the
   -- exact reviewed effective value. Once present it must not disappear or
   -- change during the sequence. The saved authority never changes here.
   if old.raw.cache[id].state~='absent'and not equal(old.raw.cache[id],new.raw.cache[id])then
    fail('management_sources_changed')end
  end
  PRIVATE[h]=new
  return true
 end)
end
-- Internal candidate planning, not a production environment writer. Retain
-- exact saved representations for unchanged values. A changed profile gets
-- invalidated managed caches so no prior-generation getter value survives.
function M.plan_sources(data,network,mode)
 return safe(function()
  if mode~='offline_synthetic'then fail('management_source_plan_mode_refused')end
  local old=inspect(data);local desired=managed_profile(network)
  local env=copy(data.environment);local caches=copy(data.cache);local count,invalidated=0,0
  for _,id in ipairs(FIELDS)do
   if old.saved[id]~=desired[id]then
    env[id]={state='value',value=desired[id]};count=count+1
   end
  end
  if count>0 then
   for id in pairs(CACHED)do
    if caches[id].state~='absent'then invalidated=invalidated+1 end
    caches[id]={state='absent'}
   end
  end
  local next_data={environment=env,cache=caches,factory_mac=copy(data.factory_mac),network=network}
  inspect(next_data)
  return {evidence=next_data,changed_sources=count,invalidated_caches=invalidated}
 end)
end
function M.report(h)
 local p=type(h)=='table'and PRIVATE[h]
 if not p then return nil,'invalid_management_source_proof'end
 return {status='SOURCE_MANAGEMENT_PRECEDENCE_ALIGNED',fields_checked=6,
  boot_cache_entries=p.cache_count,contains_configuration_values=false,
  future_reboot_proven=false,live_effect_proven=false,production_activation_allowed=false}
end
return M
