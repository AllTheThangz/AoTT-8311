-- Actual vendor fw_printenv/fw_setenv against private regular images only.
-- Used by each transaction/recovery worker process, never a physical device.
local M={}
function M.bind(root,vendor,fault)
 local n,fs=require 'nixio',require 'nixio.fs'
 local web=require '8311.webutil'
 local base=root..'/native-env'
 local id=root:match('^/var/tmp/aott%-c014%-txn%-test%-([a-f0-9]+)$')
 assert(id and #id==16)
 local config='a 0x0 0x4000 0x4000 1\nb 0x0 0x4000 0x4000 1\n'
 local identities={}
 local function same(a,b)return a and b and a.ino==b.ino and a['dev']==b['dev']end
 local function directory(p)
  local s=fs.lstat(p)
  assert(s and s.type=='dir'and s.uid==0 and s.gid==0 and s.modedec==700,'UNSAFE_NATIVE_FIXTURE_DIRECTORY')
  if identities[p]then assert(same(s,identities[p]),'NATIVE_FIXTURE_DIRECTORY_CHANGED')else identities[p]=s end
 end
 local function regular(p,size)
  local s=fs.lstat(p)
  assert(s and s.type=='reg'and s.uid==0 and s.gid==0 and s.modedec==600 and s.nlink==1 and s.size==size,'UNSAFE_NATIVE_IMAGE')
  if identities[p]then assert(same(s,identities[p]),'NATIVE_FIXTURE_FILE_CHANGED')else identities[p]=s end
 end
 local function validate()
  directory(root);directory(base);directory(base..'/locks')
  regular(base..'/a',16384);regular(base..'/b',16384);regular(base..'/fw_env.config',#config)
  assert(fs.readfile(base..'/fw_env.config',256)==config,'NATIVE_CONFIG_CHANGED')
  local marker='AOTT-NATIVE-ENV-FIXTURE-1\n'
  regular(root..'/native.environment',#marker)
  assert(fs.readfile(root..'/native.environment',64)==marker,'NATIVE_MARKER_CHANGED')
  return true
 end
 local function command(write,state,value)
  validate()
  local argv={'/usr/bin/timeout','-k','1','5','/usr/bin/env','-C',base,
   '/usr/bin/qemu-mips-static','-L',vendor,'-0',write and 'fw_setenv'or 'fw_printenv',
   vendor..'/usr/sbin/fw_printenv','-c',base..'/fw_env.config','-l','locks','--'}
  if write then
   assert(state=='unset'or(state=='value'and type(value)=='string'and value:match('^%d+$')and #value<=4))
   argv[#argv+1]='8311_lct_vlan'
   if state=='value'then argv[#argv+1]=value end
  else
   for _,key in ipairs({'ipaddr','netmask','gateway','dns_server','lct_mac','lct_vlan'})do argv[#argv+1]='8311_'..key end
  end
  return web.capture(argv,4096)
 end
 local fired=false
 local function set_vlan(state,value,ordinal,direction)
  validate()
  local path=base..'/calls.log';local prior=fs.lstat(path)
  assert(not prior or(prior.type=='reg'and prior.uid==0 and prior.modedec==600 and prior.nlink==1 and prior.size<4096))
  local fd=assert(n.open(path,n.open_flags('wronly','creat','append'),600))
  assert(fd:writeall(direction..':'..ordinal..'\n'));assert(fd:sync());assert(fd:close())
  if not fired and direction=='apply'and ordinal==2 and fault=='native_second_write_fail'then
   fired=true;return 9,'SYNTHETIC_FAILURE',false end
  if not fired and direction=='apply'and fault=='native_silent_noop'then fired=true;return 0,'',false end
  local code,raw,overflow=command(true,state,value)
  if code==0 and not fired then
   if (fault=='native_crash_after_first'and direction=='apply'and ordinal==1)or
      (fault=='native_crash_during_restore'and direction=='restore'and ordinal==1)then os.exit(87)
   elseif fault=='native_pause_after_first'and direction=='apply'and ordinal==1 then
    fired=true;io.write('AOTT_NATIVE_ENV_BARRIER:apply_one\n');io.flush()
    assert(io.read('*l')=='continue','NATIVE_BARRIER_CANCELLED')
   elseif fault=='native_pause_during_restore'and direction=='restore'and ordinal==1 then
    fired=true;io.write('AOTT_NATIVE_ENV_BARRIER:restore_one\n');io.flush()
    assert(io.read('*l')=='continue','NATIVE_BARRIER_CANCELLED')
   elseif fault=='native_error_after_write'and direction=='apply'then
    fired=true;return 9,'SYNTHETIC_POSTWRITE_FAILURE',false
   end
  end
  return code,raw,overflow
 end
 return require('8311.native_environment_guard').bind_fixture(root,
  {root=root,disposable_fixture=true,validate=validate,read=function()return command(false)end,set_vlan=set_vlan},'offline_synthetic')
end
return M
