-- Isolated, vendor-MIPS P0 test of the real webutil.write implementation.
-- Only temp paths under a host-created private directory; no ONU connection.
local source=assert(arg[1])
local dir=assert(arg[2])
package.path=source.."/?.lua;"..package.path
local nixio=require "nixio"
local fs=require "nixio.fs"
local unique=0
package.preload["luci.sys"]=function()
    return {
        uniqueid=function(bytes)
            assert(bytes==16)
            unique=unique+1
            return string.format("%032x",unique)
        end,
        process={exec=function() error("unexpected process") end},
    }
end
package.preload["luci.jsonc"]=function() return {parse=function() return nil end} end
local web=require "8311.webutil"
local created_mode={}
local original_open=nixio.open
nixio.open=function(path,flags,mode)
    local f=original_open(path,flags,mode)
    if f and path:find(".aott-write-",1,true) then
        local st=fs.lstat(path)
        assert(st and st.modedec==600,"private-stage-must-start-0600")
        created_mode[#created_mode+1]=st.modedec
    end
    return f
end

local p=dir.."/secret.pem"
local ok,why=web.write(p,"SUPER-PRIVATE-KEY\n",600)
assert(ok,why)
assert(fs.readfile(p)=="SUPER-PRIVATE-KEY\n")
assert(fs.lstat(p).modedec==600)
assert(#created_mode==1 and created_mode[1]==600)

ok,why=web.write(p,"REPLACEMENT-SECRET\n",600)
assert(ok,why)
assert(fs.readfile(p)=="REPLACEMENT-SECRET\n")
assert(fs.lstat(p).modedec==600)

local cert=dir.."/certificate.pem"
ok,why=web.write(cert,"CERTIFICATE\n",644)
assert(ok,why)
assert(fs.readfile(cert)=="CERTIFICATE\n")
assert(fs.lstat(cert).modedec==644)
assert(#created_mode==3)

local hook=dir.."/hook.sh"
ok,why=web.write(hook,"#!/bin/sh\nexit 0\n",755)
assert(ok,why)
assert(fs.lstat(hook).modedec==755)

local empty=dir.."/empty"
ok,why=web.write(empty,"",600)
assert(ok,why)
assert(fs.lstat(empty).size==0)

-- Simulate a failing atomic replacement. The old target must stay intact.
local saved_rename=fs.rename
fs.rename=function(_a,_b) return nil end
ok,why=web.write(p,"MUST-NOT-REPLACE",600)
assert(not ok and type(why)=="string")
fs.rename=saved_rename
assert(fs.readfile(p)=="REPLACEMENT-SECRET\n")
assert(fs.lstat(p).modedec==600)
local iterator=fs.dir(dir)
for name in iterator do
    assert(not name:find(".aott-write-",1,true),"temp-file-leaked")
end

-- Fail closed on nonregular destinations and input path traversal.
assert(os.execute("/bin/ln -s secret.pem "..dir.."/symlink") == 0)
ok=web.write(dir.."/symlink","ATTACK",600)
assert(not ok)
assert(fs.readfile(p)=="REPLACEMENT-SECRET\n")
ok=web.write(dir.."/../escape","ATTACK",600)
assert(not ok)
ok=web.write("relative/path","ATTACK",600)
assert(not ok)
ok=web.write(dir.."/unsupported","ATTACK",777)
assert(not ok)
ok=web.write(dir.."/huge",string.rep("x",1048577),600)
assert(not ok)

print("P0_VENDOR_MIPS_ATOMIC_WRITE_PASS")
