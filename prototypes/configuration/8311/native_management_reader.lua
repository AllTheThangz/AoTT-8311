-- Lossless READ-ONLY snapshot of exactly six management environment keys.
-- No full environment export, no caller-supplied key/path/command and no writer.
-- A single fw_printenv process reads one environment snapshot under its lock.
local M={}
local KEYS={'ipaddr','netmask','gateway','dns_server','lct_mac','lct_vlan'}
local BY_NAME={}
for _,key in ipairs(KEYS)do BY_NAME['8311_'..key]=key end
local PRIVATE=setmetatable({}, {__mode='k'})
local ERROR={}
local LIMIT=4096
local function fail(code)error({tag=ERROR,code=code},0)end
local function reason(e)
 if type(e)=='table'and rawget(e,'tag')==ERROR then return rawget(e,'code')end
 return 'native_management_read_internal_error'
end
local function safe(fn,...)
 local ok,a=pcall(fn,...)
 if not ok then return nil,reason(a)end
 return a
end
local function decode(code,raw,overflow,kind)
 if overflow~=false then fail('native_management_output_unbounded')end
 if code~=0 and code~=1 then fail('native_management_command_failed')end
 if type(raw)~='string'or #raw>LIMIT or raw==''or raw:sub(-1)~='\n' or
    raw:find('[%z\1-\9\11-\31\127]')then fail('native_management_output_invalid')end
 local records={};local count,missing,present,empty=0,0,0,0
 for line in raw:gmatch('([^\n]*)\n')do
  local name,value=line:match('^([a-zA-Z0-9_]+)=(.*)$')
  local state='value'
  if not name then
   name=line:match('^## Error: "([a-zA-Z0-9_]+)" not defined$')
   state='unset'
  end
  local key=name and BY_NAME[name]
  if not key or records[key]then fail('native_management_unexpected_output')end
  if state=='value'then
   if #value>128 then fail('native_management_value_too_large')end
   records[key]={state='value',value=value};present=present+1
   if value==''then empty=empty+1 end
  else
   records[key]={state='unset'};missing=missing+1
  end
  count=count+1
 end
 if count~=#KEYS then fail('native_management_snapshot_incomplete')end
 if (code==0 and missing~=0)or(code==1 and missing==0)then
  fail('native_management_exit_mismatch')end
 local handle={}
 PRIVATE[handle]={records=records,present=present,unset=missing,present_empty=empty,kind=kind}
 return handle
end
local function private(handle)
 local p=type(handle)=='table'and PRIVATE[handle]
 if not p then fail('invalid_native_management_snapshot')end
 return p
end
function M.read()
 return safe(function()
  -- No -n: the NAME= header preserves an empty value. No -l override:
  -- the vendor's default advisory lock must protect its real environment.
  local argv={'/usr/bin/timeout','-k','1','5','/usr/sbin/fw_printenv','--'}
  for _,key in ipairs(KEYS)do argv[#argv+1]='8311_'..key end
  local code,raw,overflow=require('8311.webutil').capture(argv,LIMIT)
  return decode(code,raw,overflow,'native_scoped_reader')
 end)
end
function M.fixture_decode(code,raw,overflow,mode)
 return safe(function()
  if mode~='offline_synthetic'then fail('native_reader_fixture_mode_refused')end
  return decode(code,raw,overflow,'synthetic_parser_fixture')
 end)
end
-- Private integration accessor. Values are not telemetry; do not serialize
-- this accessor into a web response, support report or shared diagnostic log.
function M.records(handle)
 return safe(function()
  local p=private(handle);local out={}
  for _,key in ipairs(KEYS)do
   local entry=p.records[key];out[key]={state=entry.state}
   if entry.state=='value'then out[key].value=entry.value end
  end
  return out
 end)
end
function M.same(a,b)
 return safe(function()
  local x,y=private(a),private(b)
  for _,key in ipairs(KEYS)do
   if x.records[key].state~=y.records[key].state or x.records[key].value~=y.records[key].value then
    return false end
  end
  return true
 end)
end
function M.summary(handle)
 return safe(function()
  local p=private(handle);local states={}
  for _,key in ipairs(KEYS)do
   local entry=p.records[key]
   states[key]=entry.state=='unset'and 'unset'or(entry.value==''and 'present_empty'or 'present_value')
  end
  return {status='SCOPED_MANAGEMENT_SNAPSHOT_READ',fields=6,states=states,
   present=p.present,unset=p.unset,present_empty=p.present_empty,
   basis=p.kind,contains_configuration_values=false,full_environment_exported=false,
   native_setter_invocations=0,write_authorized=false,
   wrapper_cannot_restore_present_empty=p.present_empty>0,
   cache_or_boot_state_verified=false}
 end)
end
return M
