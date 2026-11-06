-- Cooperative native-environment operation lock. Disposable scope only.
-- Uses BSD flock, matching the vendor shell wrapper, NOT nixio's lockf.
-- Acquired after transaction.lock; retained through that complete operation.
-- A live-device path and production permission are deliberately not provided.
local M={}
local ERROR={}
local OWNERS={}
local TOKENS=setmetatable({}, {__mode='k'})
local function fail(code)error({tag=ERROR,code=code},0)end
local function reason(v)
 if type(v)=='table'and rawget(v,'tag')==ERROR then return rawget(v,'code')end
 return 'environment_lease_internal_error'
end
local function allowed(root,mode)
 if mode~='offline_synthetic'or type(root)~='string'then return false end
 local id=root:match('^/var/tmp/aott%-c014%-txn%-test%-([a-f0-9]+)$')
 return id and #id==16
end
local function same(a,b)return a and b and a.ino==b.ino and a['dev']==b['dev']end
local function directory(s)return s and s.type=='dir'and s.uid==0 and s.gid==0 and s.modedec==700 end
local function regular(s)return s and s.type=='reg'and s.uid==0 and s.gid==0 and s.modedec==600 and s.nlink==1 and s.size==0 end
local function close(fd)
 if not fd then return true end
 local ok,value=pcall(function()return fd:close()end)
 return ok and value==true
end
local function check(c)
 if c.n.getpid()~=c.pid then fail('environment_lease_process_changed')end
 if not directory(c.fs.lstat(c.root))or not same(c.fs.lstat(c.root),c.parent)or
    not directory(c.fs.lstat(c.base))or not same(c.fs.lstat(c.base),c.directory)then
  fail('environment_lease_directory_changed')end
 local visible,opened=c.fs.lstat(c.path),c.fd:stat()
 if not regular(visible)or not regular(opened)or not same(visible,c.inode)or not same(opened,c.inode)then
  fail('environment_lease_inode_changed')end
end
local function command(c,args)
 local argv={'/usr/bin/timeout','-k','1','3','/usr/bin/flock'}
 for _,arg in ipairs(args)do argv[#argv+1]=arg end
 local code,raw,overflow=c.web.capture(argv,256)
 if type(code)~='number'or raw~=''or overflow~=false then fail('environment_lease_helper_failed')end
 return code
end
function M.acquire(root,mode)
 if not allowed(root,mode)then return nil,'environment_lease_scope_refused'end
 if OWNERS[root]then return nil,'environment_lease_already_owned'end
 local c,fd
 local ok,result=pcall(function()
  local n,fs=require 'nixio',require 'nixio.fs'
  local base=root..'/native-env'
  c={root=root,base=base,path=base..'/8311-environment.lock',n=n,fs=fs,
     web=require '8311.webutil',pid=n.getpid(),parent=fs.lstat(root),directory=fs.lstat(base)}
  if not directory(c.parent)or not directory(c.directory)then fail('environment_lease_unsafe_directory')end
  local old,errno=fs.lstat(c.path)
  if not old and errno~=2 then fail('environment_lease_path_unavailable')end
  if old and not regular(old)then fail('environment_lease_unsafe_file')end
  fd=n.open(c.path,old and n.open_flags('rdwr')or n.open_flags('rdwr','creat','excl'),600)
  if not fd then fail('environment_lease_open_failed')end
  c.fd=fd;c.inode=fd:stat()
  if not regular(c.inode)or(old and not same(old,c.inode))then fail('environment_lease_inode_changed')end
  check(c)
  -- nixio's checked file userdata renders its descriptor using this fixed
  -- upstream format. No caller-controlled descriptor or command is accepted.
  local number=tonumber(tostring(fd):match('^nixio file (%d+)$'))
  if not number or number<3 or number>1048575 then fail('environment_lease_descriptor_unavailable')end
  if not same(fs.stat('/proc/self/fd/'..number),c.inode)then fail('environment_lease_descriptor_changed')end
  local code=command(c,{'-n',tostring(number)})
  if code==1 then fail('environment_lease_busy')end
  if code~=0 then fail('environment_lease_helper_failed')end
  check(c)
  -- A new open-file description must conflict after the short helper exits.
  -- This proves the caller retained the flock, rather than a dead child PID
  -- or stale marker being mistaken for lock ownership.
  if command(c,{'-n',c.path,'/bin/true'})~=1 then fail('environment_lease_not_retained')end
  check(c)
  if not old then
   if fd:sync()~=true then fail('environment_lease_sync_failed')end
   local d=n.open(base,n.open_flags('rdonly'))
   if not d then fail('environment_lease_sync_failed')end
   local synced=d:sync();local closed=close(d)
   if synced~=true or not closed then fail('environment_lease_sync_failed')end
  end
  local handle={};TOKENS[handle]=c;OWNERS[root]=handle;return handle
 end)
 if not ok then
  if not close(fd)then OWNERS[root]={};return nil,'environment_lease_release_unverified'end
  return nil,reason(result)
 end
 return result
end
function M.verify(handle)
 local c=type(handle)=='table'and TOKENS[handle]
 if not c or OWNERS[c.root]~=handle then return nil,'invalid_environment_lease'end
 local ok,e=pcall(check,c)
 if not ok then return nil,reason(e)end
 return true
end
function M.require_owned(root,mode)
 if not allowed(root,mode)then return nil,'environment_lease_scope_refused'end
 local h=OWNERS[root]
 if not h then return nil,'environment_lease_required'end
 return M.verify(h)
end
function M.close(handle)
 local c=type(handle)=='table'and TOKENS[handle]
 if not c or OWNERS[c.root]~=handle then return nil,'invalid_environment_lease'end
 if c.n.getpid()~=c.pid then return nil,'environment_lease_process_changed'end
 -- Never unlink the shared inode or issue flock -u through an inherited
 -- descriptor. Closing our reference releases it after synchronous children
 -- have exited; a crashed child's bounded native command may briefly retain it.
 if not close(c.fd)then return nil,'environment_lease_release_unverified'end
 TOKENS[handle]=nil;OWNERS[c.root]=nil
 return true
end
return M
