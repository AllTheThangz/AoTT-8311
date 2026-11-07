-- Canonical scoped startup-state records for the synthetic native transaction.
-- No real firmware environment, cache path, service or device access. Each
-- field records absence versus an empty value explicitly; neither is guessed.
local M={}
local ERROR={}
local ENV={'ipaddr','netmask','gateway','dns_server','lct_mac','lct_vlan','factory_mac'}
local CACHE={'ipaddr','netmask','gateway','dns_server','lct_mac'}
local function fail(code)error({tag=ERROR,code=code},0)end
local function safe(fn,...)
 local ok,result=pcall(fn,...)
 if ok then return result end
 if type(result)=='table'and rawget(result,'tag')==ERROR then return nil,rawget(result,'code')end
 return nil,'startup_state_internal_error'
end
local function plain(v)return type(v)=='table'and getmetatable(v)==nil end
local function valid_text(v)return type(v)=='string'and #v<=128 and not v:find('[%z\1-\31\127]')end
local function to_hex(v)return (v:gsub('.',function(c)return string.format('%02x',c:byte())end))end
local function from_hex(v)
 if #v>256 or #v%2~=0 or v:find('[^a-f0-9]')then fail('startup_state_record_invalid')end
 return (v:gsub('%x%x',function(c)return string.char(tonumber(c,16))end))
end
local function encode(kind,records)
 local keys=kind=='ENV'and ENV or CACHE
 if kind~='ENV'and kind~='CACHE'then fail('startup_state_kind_invalid')end
 if not plain(records)then fail('startup_state_records_invalid')end
 local expected={};for _,key in ipairs(keys)do expected[key]=true end
 for k in pairs(records)do if not expected[k]then fail('startup_state_scope_invalid')end end
 local rows={'AOTT-MGMT-'..kind..'-1'}
 for _,key in ipairs(keys)do
  local item=records[key]
  if not plain(item)then fail('startup_state_record_invalid')end
  for k in pairs(item)do if k~='state'and k~='value'then fail('startup_state_record_invalid')end end
  local missing=(kind=='CACHE'or key=='factory_mac')and 'absent'or 'unset'
  if item.state==missing and item.value==nil then rows[#rows+1]=key..' '..missing
  elseif item.state=='value'and valid_text(item.value)then rows[#rows+1]=key..' value '..to_hex(item.value)
  else fail('startup_state_record_invalid')end
 end
 return table.concat(rows,'\n')..'\n'
end
local function decode(kind,raw)
 local keys=kind=='ENV'and ENV or CACHE
 if type(raw)~='string'or #raw>4096 then fail('startup_state_size_invalid')end
 local rows={};for line in raw:gmatch('([^\n]*)\n')do rows[#rows+1]=line end
 if #rows~=#keys+1 or rows[1]~='AOTT-MGMT-'..kind..'-1'then fail('startup_state_record_invalid')end
 local out={}
 for i,key in ipairs(keys)do
  local prefix=key..' ';local line=rows[i+1]
  if line:sub(1,#prefix)~=prefix then fail('startup_state_record_invalid')end
  local item=line:sub(#prefix+1)
  local missing=(kind=='CACHE'or key=='factory_mac')and 'absent'or 'unset'
  if item==missing then out[key]={state=missing}
  elseif item:sub(1,6)=='value 'then out[key]={state='value',value=from_hex(item:sub(7))}
  else fail('startup_state_record_invalid')end
 end
 if encode(kind,out)~=raw then fail('startup_state_record_invalid')end
 return out
end
local function evidence(environment,cache,network)
 local e=decode('ENV',environment);local c=decode('CACHE',cache)
 local factory=e.factory_mac;e.factory_mac=nil
 return {environment=e,cache=c,factory_mac=factory,network=network}
end
function M.encode_environment(records)return safe(encode,'ENV',records)end
function M.encode_cache(records)return safe(encode,'CACHE',records)end
function M.evidence(environment,cache,network)return safe(evidence,environment,cache,network)end
function M.verify(environment,cache,network)
 return safe(function()
  local data=evidence(environment,cache,network)
  local sources=require '8311.management_sources'
  local h=sources.review(data)
  if not h then fail('startup_state_source_disagreement')end
  return sources.report(h)
 end)
end
function M.plan(environment,cache,before_network,after_network,mode)
 return safe(function()
  if mode~='offline_synthetic'then fail('startup_state_mode_refused')end
  local sources=require '8311.management_sources'
  local data=evidence(environment,cache,before_network)
  local planned=sources.plan_sources(data,after_network,mode)
  if not planned then fail('startup_state_plan_unqualified')end
  local e=planned.evidence.environment;e.factory_mac=planned.evidence.factory_mac
  local encoded_env=encode('ENV',e);local encoded_cache=encode('CACHE',planned.evidence.cache)
  if not M.verify(encoded_env,encoded_cache,after_network)then fail('startup_state_candidate_disagrees')end
  return {environment=encoded_env,cache=encoded_cache,changed_sources=planned.changed_sources,
          invalidated_caches=planned.invalidated_caches,source_only_not_deployed=true}
 end)
end
return M
