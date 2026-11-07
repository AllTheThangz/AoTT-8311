-- Guarded native management environment mutation, fixture binding ONLY.
-- Integrated by vlan_transaction after its pending recovery decision is saved.
-- The initial write scope is one canonical VLAN override, not arbitrary env.
-- No production transport or live-device path is installed by this module.
local M={}
local ERROR={}
local BOUND={}
local KEYS={'ipaddr','netmask','gateway','dns_server','lct_mac','lct_vlan'}
local function fail(code)error({tag=ERROR,code=code},0)end
local function safe(fn,...)
 local ok,a=pcall(fn,...)
 if ok then return a end
 if type(a)=='table'and rawget(a,'tag')==ERROR then return nil,rawget(a,'code')end
 return nil,'native_environment_internal_error'
end
local function authorized(root,mode)
 if mode~='offline_synthetic'or type(root)~='string'then return false end
 local id=root:match('^/var/tmp/aott%-c014%-txn%-test%-([a-f0-9]+)$')
 return id and #id==16
end
local function plain(t)return type(t)=='table'and getmetatable(t)==nil end
local function equal(a,b)
 return a.state==b.state and a.value==b.value
end
local function records(value)
 if not plain(value)then fail('native_environment_snapshot_invalid')end
 local allowed={};for _,key in ipairs(KEYS)do allowed[key]=true end
 for key in pairs(value)do if not allowed[key]then fail('native_environment_snapshot_scope')end end
 local out={}
 for _,key in ipairs(KEYS)do
  local item=value[key]
  if not plain(item)then fail('native_environment_snapshot_invalid')end
  for name in pairs(item)do if name~='state'and name~='value'then fail('native_environment_snapshot_invalid')end end
  if item.state=='unset'and item.value==nil then out[key]={state='unset'}
  elseif item.state=='value'and type(item.value)=='string'and #item.value<=128 and
      not item.value:find('[%z\1-\31\127]')then out[key]={state='value',value=item.value}
  else fail('native_environment_snapshot_invalid')end
 end
 return out
end
local function plan(before,after)
 before=records(before);after=records(after)
 local changed=not equal(before.lct_vlan,after.lct_vlan)
 for _,key in ipairs(KEYS)do
  if key~='lct_vlan'and not equal(before[key],after[key])then fail('native_environment_write_scope_refused')end
 end
 if changed then
  for _,item in ipairs({before.lct_vlan,after.lct_vlan})do
   if item.state=='value'then
    if item.value==''then fail('native_environment_empty_restore_unsupported')end
    local n=tonumber(item.value)
    if not item.value:match('^%d+$')or #item.value>4 or not n or n>4094 or tostring(n)~=item.value then
     fail('native_environment_vlan_unqualified')end
   end
  end
 end
 return {before=before,after=after,changed=changed}
end
function M.bind_fixture(root,transport,mode)
 return safe(function()
  if not authorized(root,mode)then fail('native_environment_mode_refused')end
  if BOUND[root]then fail('native_environment_already_bound')end
  if not plain(transport)or transport.root~=root or transport.disposable_fixture~=true or
     type(transport.validate)~='function'or type(transport.read)~='function'or type(transport.set_vlan)~='function'then
   fail('native_environment_transport_refused')end
  if transport.validate()~=true then fail('native_environment_transport_unverified')end
  -- Capture functions privately so later modification of caller's table does
  -- not change which backend executes a pending journal.
  BOUND[root]={root=root,validate=transport.validate,read=transport.read,set_vlan=transport.set_vlan}
  return true
 end)
end
local function transport(root,mode)
 if not authorized(root,mode)then fail('native_environment_mode_refused')end
 local t=BOUND[root]
 if not t then fail('native_environment_backend_missing')end
 local owned,why=require('8311.environment_lease').require_owned(root,mode)
 if not owned then fail(why)end
 if t.validate()~=true then fail('native_environment_transport_unverified')end
 return t
end
local function observe(t,p)
 local owned,why=require('8311.environment_lease').require_owned(t.root,'offline_synthetic')
 if not owned then fail(why)end
 if t.validate()~=true then fail('native_environment_transport_unverified')end
 local reader=require '8311.native_management_reader'
 local code,raw,overflow=t.read()
 local snapshot=reader.fixture_decode(code,raw,overflow,'offline_synthetic')
 if not snapshot then fail('native_environment_read_unverified')end
 local current=reader.records(snapshot)
 if not current or t.validate()~=true then fail('native_environment_read_unverified')end
 local before,after=true,true
 for _,key in ipairs(KEYS)do
  before=before and equal(current[key],p.before[key])
  after=after and equal(current[key],p.after[key])
 end
 if not before and not after then fail('native_environment_external_change')end
 return {before=before,after=after,changed=p.changed}
end
function M.plan(before,after,mode)
 return safe(function()
  if mode~='offline_synthetic'then fail('native_environment_mode_refused')end
  local p=plan(before,after)
  return {changed=p.changed,field_count=p.changed and 1 or 0,
          present_empty_unchanged_preserved=true,production_write_allowed=false}
 end)
end
function M.inspect(root,before,after,mode)
 return safe(function()return observe(transport(root,mode),plan(before,after))end)
end
function M.change(root,before,after,direction,boundary,mode)
 return safe(function()
  if direction~='apply'and direction~='restore'then fail('native_environment_direction_refused')end
  if type(boundary)~='function'then fail('native_environment_boundary_required')end
  local p=plan(before,after);local t=transport(root,mode)
  local state=observe(t,p)
  if not p.changed then return {status='SOURCE_NATIVE_ENV_NO_CHANGE',native_calls=0}end
  local desired=direction=='apply'and p.after.lct_vlan or p.before.lct_vlan
  -- Both calls are intentional, including after a previous caller crashed
  -- after call one. A matching selected copy alone does not prove redundancy.
  for ordinal=1,2 do
   if boundary()~=true then fail('native_environment_boundary_lost')end
   observe(t,p)
   local code,raw,overflow=t.set_vlan(desired.state,desired.value,ordinal,direction)
   if code~=0 or raw~=''or overflow~=false then fail('native_environment_write_failed')end
   state=observe(t,p)
   if (direction=='apply'and not state.after)or(direction=='restore'and not state.before)then
    fail('native_environment_write_readback_mismatch')end
  end
  if boundary()~=true then fail('native_environment_boundary_lost')end
  state=observe(t,p)
  if (direction=='apply'and not state.after)or(direction=='restore'and not state.before)then
   fail('native_environment_write_readback_mismatch')end
  return {status='SOURCE_NATIVE_ENV_CHANGE_VERIFIED',native_calls=2,
          physical_durability_unqualified=true,live_device_changed=false}
 end)
end
return M
