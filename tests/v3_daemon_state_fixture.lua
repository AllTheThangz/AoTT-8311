local root=assert(arg[1],"overlay lua root required")
package.path=root.."/?.lua;"..package.path

local function ip(a,b,c,d) return table.concat({a,b,c,d},".") end
local TARGET=ip("192","0","2","1")
local BAD_TARGET=ip("999","0","2","1")

local current_boot="12345678-1234-1234-1234-123456789abc"
local files={
 ["/proc/sys/kernel/random/boot_id"]=current_boot.."\n",
 ["/var/run/aott-runtime/pingd.state"]=table.concat({
   "schema=1","pid=101","boot_id="..current_boot,
   "enabled=1","active=1","target="..TARGET,""
 },"\n"),
 ["/var/run/aott-runtime/rarpd.state"]=table.concat({
   "schema=1","pid=102","boot_id="..current_boot,
   "enabled=1","active=0",""
 },"\n"),
 ["/proc/101/cmdline"]="/bin/sh\0/usr/sbin/8311-pingd.sh\0",
 ["/proc/102/cmdline"]="/bin/sh\0/usr/sbin/8311-rarpd.sh\0",
}
local modes={
 ["/var/run/aott-runtime"]={type="dir",uid=0,gid=0,modedec=700},
 ["/var/run/aott-runtime/pingd.state"]={type="reg",uid=0,gid=0,modedec=600,nlink=1,size=#files["/var/run/aott-runtime/pingd.state"]},
 ["/var/run/aott-runtime/rarpd.state"]={type="reg",uid=0,gid=0,modedec=600,nlink=1,size=#files["/var/run/aott-runtime/rarpd.state"]},
}
package.preload["nixio.fs"]=function()
 local M={}
 function M.lstat(path) return modes[path] end
 function M.readfile(path,limit)
   local value=files[path]
   if type(value)~="string" then return nil end
   if limit and #value>limit then return value:sub(1,limit) end
   return value
 end
 return M
end

local state=require "8311.daemon_state"
local checks=0
local function eq(a,b,label)
 checks=checks+1
 assert(a==b,"DAEMON_STATE_FIXTURE:"..label.." expected="..tostring(b).." got="..tostring(a))
end

local ping=assert(state.read("pingd"))
eq(ping.schema,1,"ping_schema")
eq(ping.pid,101,"ping_pid")
eq(ping.enabled,true,"ping_enabled")
eq(ping.active,true,"ping_active")
eq(ping.target,TARGET,"ping_target")
eq(ping.process_identity_verified,true,"ping_identity")

local rarp=assert(state.read("rarpd"))
eq(rarp.enabled,true,"rarp_enabled")
eq(rarp.active,false,"rarp_idle")
eq(rarp.target,nil,"rarp_no_target")
eq(rarp.process_identity_verified,true,"rarp_identity")

local original=files["/var/run/aott-runtime/pingd.state"]
files["/var/run/aott-runtime/pingd.state"]=original:gsub("boot_id=[^\n]+","boot_id=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",1)
local bad,why=state.read("pingd")
eq(bad,nil,"stale_boot_rejected")
eq(why,"runtime_boot_mismatch","stale_boot_reason")
files["/var/run/aott-runtime/pingd.state"]=original

files["/proc/101/cmdline"]="/bin/sh\0/usr/sbin/not-pingd.sh\0"
bad,why=state.read("pingd")
eq(bad,nil,"wrong_process_rejected")
eq(why,"runtime_process_identity_mismatch","wrong_process_reason")
files["/proc/101/cmdline"]="/bin/sh\0/usr/sbin/8311-pingd.sh\0"

local oldmode=modes["/var/run/aott-runtime/pingd.state"].modedec
modes["/var/run/aott-runtime/pingd.state"].modedec=644
bad,why=state.read("pingd")
eq(bad,nil,"unsafe_mode_rejected")
eq(why,"runtime_state_file_unavailable","unsafe_mode_reason")
modes["/var/run/aott-runtime/pingd.state"].modedec=oldmode

files["/var/run/aott-runtime/pingd.state"]=original:gsub("target="..TARGET:gsub("%.","%%."),"target="..BAD_TARGET)
bad,why=state.read("pingd")
eq(bad,nil,"bad_target_rejected")
eq(why,"runtime_target_invalid","bad_target_reason")
files["/var/run/aott-runtime/pingd.state"]=original

bad,why=state.read("unknown")
eq(bad,nil,"unknown_rejected")
eq(why,"unknown_daemon_state","unknown_reason")

eq(checks>=20,true,"substantial")
print("AOTT_V3_DAEMON_STATE_PASS checks="..checks)
