local root=assert(arg[1],"overlay lua root required")
package.path=root.."/?.lua;"..package.path

local direct="lct"
local process_device="eth0_0_1_lct"
local raw="package 'dropbear'\nconfig dropbear\n\toption DirectInterface 'lct'\n"

package.preload["nixio.fs"]=function()
    return {
        readfile=function(path)
            if path=="/proc/123/cmdline" then
                return "/usr/sbin/dropbear\0-F\0-P\0/var/run/dropbear.1.pid\0-l\0"..
                    process_device.."\0-p\022\0"
            end
        end,
        lstat=function(path)
            if path=="/ptconf/8311/aott-recovery/v1/management/dropbear.before" then
                return {type="reg",uid=0,gid=0,modedec=600,nlink=1,size=#raw}
            end
        end,
    }
end

package.preload["8311.webutil"]=function()
    return {capture=function(argv)
        if argv[1]=="/sbin/uci" and argv[2]=="export" and argv[3]=="dropbear" then
            return 0,raw,false
        elseif argv[1]=="/etc/init.d/dropbear" and argv[2]=="restart" then
            process_device=direct=="mgmt" and "mgmt" or "eth0_0_1_lct"
            return 0,"",false
        elseif argv[1]=="/bin/pidof" and argv[2]=="dropbear" then
            return 0,"123\n",false
        elseif argv[1]=="/sbin/uci" and argv[2]=="-f" then
            return 0,"",false
        elseif argv[1]=="/sbin/uci" and argv[2]=="commit" and argv[3]=="dropbear" then
            return 0,"",false
        end
        return 1,"",false
    end}
end

package.preload["luci.model.uci"]=function()
    local cursor={}
    function cursor:foreach(pkg,kind,cb)
        assert(pkg=="dropbear" and kind=="dropbear")
        cb({[".name"]="cfg"})
    end
    function cursor:get(pkg,section,option)
        assert(pkg=="dropbear" and section=="cfg" and option=="DirectInterface")
        return direct
    end
    function cursor:set(pkg,section,option,value)
        assert(pkg=="dropbear" and section=="cfg" and option=="DirectInterface")
        direct=value
        return true
    end
    function cursor:commit(pkg)
        assert(pkg=="dropbear")
        return true
    end
    return {cursor=function() return cursor end}
end

local M=require "8311.management_access"
local checks=0
local function same(a,b,label)
    checks=checks+1
    assert(a==b,"MANAGEMENT_ACCESS_FIXTURE:"..label.." expected="..tostring(b).." got="..tostring(a))
end

local snap=assert(M.snapshot())
same(snap.direct_interface,"lct","snapshot_lct")
local pre=assert(M.preflight(100))
same(pre.current_interface,"lct","pre_current")
same(pre.requested_interface,"mgmt","pre_target")
same(pre.change_required,true,"pre_change")

local receipt=assert(M.apply(snap,100))
same(receipt.changed,true,"apply_changed")
same(direct,"mgmt","uci_moved")
local no,why=M.verify(100)
same(no,nil,"verify_before_restart_refused")
same(why,"dropbear_master_binding_mismatch","verify_before_restart_reason")
assert(M.reload())
local verified=assert(M.verify(100))
same(verified.status,"MANAGEMENT_SSH_BINDING_VERIFIED","verify_tagged")
same(verified.logical_interface,"mgmt","verify_tagged_interface")

snap=assert(M.snapshot())
receipt=assert(M.apply(snap,0))
same(receipt.changed,true,"apply_untagged_changed")
assert(M.reload())
verified=assert(M.verify(0))
same(verified.logical_interface,"lct","verify_untagged")

direct="custom"
local invalid,invalid_why=M.snapshot()
same(invalid,nil,"custom_binding_refused")
same(invalid_why,"dropbear_direct_interface_unqualified","custom_binding_reason")
direct="lct"

same(M.desired("4094"),"mgmt","max_vlan")
same(M.desired("0"),"lct","zero_vlan")
same(M.desired("4095"),nil,"reject_4095")

assert(checks>=14)
print("AOTT_V3_MANAGEMENT_ACCESS_PASS checks="..checks)
