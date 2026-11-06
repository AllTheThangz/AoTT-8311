-- Early boot reconciliation plus ordered post-consumer revalidation.
-- SOURCE ONLY: exact synthetic roots, no service execution, no boot env writes.
-- Reconciliation must precede defaults; later defaults/environment consumers
-- cannot be assumed harmless. A changed restored state revokes permission.
local M={}
local TOKENS=setmetatable({}, {__mode='k'})
local ORDER={'defaults_completed','sysinit_completed','before_network','netinit_completed','before_https'}
local ERROR={}
local function fail(code)error({tag=ERROR,code=code},0)end
local function reason(e)
 if type(e)=='table' and rawget(e,'tag')==ERROR then return rawget(e,'code') end
 return 'boot_recovery_internal_error'
end
local function safe(fn,...)
 local ok,value=pcall(fn,...)
 if not ok then return nil,reason(value) end
 return value
end
local function authorized(root,mode)
 if mode~='offline_synthetic' or type(root)~='string' then return false end
 local s=root:match('^/var/tmp/aott%-c014%-txn%-test%-([a-f0-9]+)$')
 return s and #s==16
end
local function same(a,b)return a and b and a.ino==b.ino and a['dev']==b['dev']end
local function directory(s)return s and s.type=='dir' and s.uid==0 and s.gid==0 and s.modedec==700 end
local function boot(fs)
 local raw=fs.readfile('/proc/sys/kernel/random/boot_id',64)
 if type(raw)~='string' or #raw~=37 or not raw:match('^[a-f0-9]+%-[a-f0-9]+%-[a-f0-9]+%-[a-f0-9]+%-[a-f0-9]+\n$') then
  fail('boot_identity_unavailable') end
 return raw
end
local function optional(fs,path)
 local st,errno=fs.lstat(path)
 if st then return st end
 if errno~=2 then fail('boot_workspace_unavailable') end
end
local function no_orphan(fs,root)
 for _,prefix in ipairs({'previous.network','previous.firewall','candidate.network','candidate.firewall',
                         'previous.environment','previous.cache','candidate.environment','candidate.cache','retained.state','transaction.state'}) do
  if optional(fs,root..'/'..prefix) or optional(fs,root..'/'..prefix..'.new') then
   fail('boot_recovery_incomplete_preparation') end
 end
end
local function check_directory(p)
 local root=p.fs.lstat(p.root);local active=p.fs.lstat(p.root..'/active')
 if not directory(root) or not directory(active) or not same(root,p.parent) or not same(active,p.active) then
  fail('boot_recovery_workspace_changed') end
 if boot(p.fs)~=p.boot then fail('boot_identity_changed') end
end
local function source_evidence(p,initial)
 local good,data=pcall(p.adapter.read)
 if not good then fail('boot_management_source_read_failed')end
 local model=require '8311.management_sources'
 local result,why
 if initial then result,why=model.review(data)
 else result,why=model.verify(p.source_proof,data)end
 if not result then fail('boot_'..why)end
 if initial then p.source_proof=result end
end
local function validate(p)
 check_directory(p)
 local tx=require '8311.vlan_transaction'
 local offer,why=tx.recovery_offer(p.root,'offline_synthetic')
 if p.unarmed then
  if offer or why~='transaction_not_armed' then fail('boot_recovery_state_changed') end
  no_orphan(p.fs,p.root)
 else
  if not offer or offer.transaction_id~=p.id or offer.phase~=p.phase then fail('boot_recovery_state_changed') end
  local verified=tx.recover(p.root,'offline_synthetic',false)
  if not verified or verified.transaction_id~=p.id or verified.phase~=p.phase then
   fail('boot_recovery_content_changed') end
 end
 check_directory(p)
 source_evidence(p,false)
end
function M.reconcile(root,mode,adapter)
 return safe(function()
  if not authorized(root,mode) then fail('boot_recovery_scope_refused') end
  if type(adapter)~='table'or getmetatable(adapter)~=nil or adapter.disposable_fixture~=true or
     adapter.root~=root or type(adapter.read)~='function'then fail('boot_management_source_adapter_required')end
  local fs=require 'nixio.fs'
  local p={root=root,fs=fs,parent=fs.lstat(root),active=fs.lstat(root..'/active'),boot=boot(fs),next_step=1,adapter=adapter}
  check_directory(p)
  local tx=require '8311.vlan_transaction'
  local offer,why=tx.recovery_offer(root,mode)
  if not offer then
   if why~='transaction_not_armed' then fail('boot_recovery_unverified') end
   no_orphan(fs,root);p.unarmed=true
  else
   -- Boot cannot preserve an unconfirmed change merely because its old
   -- process or deadline has disappeared. Restore with the real native path.
   local result=tx.recover(root,mode,false)
   if not result or (result.phase~='rolled_back' and result.phase~='confirmed') then
    fail('boot_recovery_unverified') end
   p.id=result.transaction_id;p.phase=result.phase
  end
  source_evidence(p,true)
  validate(p)
  local h={};TOKENS[h]=p;return h
 end)
end
function M.after(handle,consumer,mode)
 return safe(function()
  local p=type(handle)=='table' and TOKENS[handle]
  if not p or mode~='offline_synthetic' then fail('invalid_boot_recovery_handle') end
  if p.failed or p.complete or consumer~=ORDER[p.next_step] then fail('boot_recovery_order_invalid') end
  local ok,why=pcall(validate,p)
  if not ok then p.failed=true;fail(reason(why)) end
  p.next_step=p.next_step+1
  p.complete=p.next_step>#ORDER
  return {status=p.complete and 'SOURCE_BOOT_RECONCILIATION_CHECKED' or 'SOURCE_BOOT_CONSUMER_CHECKED',
   phase=p.phase or 'unarmed',source_only_not_deployed=true,production_activation_allowed=false,
   contains_configuration_values=false,live_startup_hooks_installed=false,source_precedence_verified=true}
 end)
end
return M
