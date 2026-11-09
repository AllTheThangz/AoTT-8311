local root=assert(arg[1],"overlay lua root required")
package.path=root.."/?.lua;"..package.path

local oldhash="$6$oldsalt$"..string.rep("A",86)
local newhash="$6$newsalt$"..string.rep("B",86)
local shadow="root:"..oldhash..":0:0:99999:7:::\ndaemon:*:0:0:99999:7:::\n"
local files={["/etc/shadow"]=shadow}
local fail_dir_sync=false
local current_hash=oldhash

package.preload["nixio.fs"]=function()
    local M={}
    function M.lstat(path)
        local data=files[path]
        if not data then return nil end
        return {type="reg",uid=0,gid=0,modedec=600,nlink=1,size=#data}
    end
    function M.readfile(path,maximum)
        local data=files[path]
        if not data then return nil end
        return data:sub(1,maximum or #data)
    end
    function M.rename(src,dst)
        if not files[src] then return false end
        files[dst]=files[src];files[src]=nil
        if dst=="/etc/shadow" then
            current_hash=files[dst]:match("^root:([^:]*):")
        end
        return true
    end
    function M.unlink(path) files[path]=nil;return true end
    return M
end

package.preload["nixio"]=function()
    local M={}
    function M.crypt(_,hash) return hash.."x" end
    function M.getpid() return 77 end
    function M.open_flags(...) return {...} end
    function M.getsp(user)
        assert(user=="root")
        return {pwdp=current_hash}
    end
    function M.open(path,flags,mode)
        if path=="/etc" then
            return {
                sync=function()
                    if fail_dir_sync then fail_dir_sync=false; return false end
                    return true
                end,
                close=function() return true end,
            }
        end
        assert(path=="/etc/.shadow.aott.77")
        assert(mode==600)
        assert(files[path]==nil)
        return {
            writeall=function(_,data) files[path]=data;return #data end,
            sync=function() return true end,
            close=function() return true end,
        }
    end
    return M
end

local module=require "8311.credential_activation"
local checks=0
local function same(a,b,label)
    checks=checks+1
    assert(a==b,"CREDENTIAL_ACTIVATION:"..label.." expected="..tostring(b).." got="..tostring(a))
end

local result=assert(module.apply(newhash))
same(result.success,true,"apply_success")
same(result.credential_verified,true,"credential_verified")
same(result.contains_credential_material,false,"redacted")
same(current_hash,newhash,"live_changed")
same(files["/etc/shadow"]:find(newhash,1,true)~=nil,true,"shadow_contains_new")

local nochange=assert(module.apply(newhash))
same(nochange.changed,false,"nochange")

local restored=assert(module.restore(oldhash))
same(restored.success,true,"restore_success")
same(current_hash,oldhash,"live_restored")

-- A failure after rename must restore the previous hash.
fail_dir_sync=true
local bad,why=module.apply(newhash)
same(bad,nil,"failure_return")
same(type(why),"string","failure_reason")
same(current_hash,oldhash,"failure_restored_live")
same(files["/etc/shadow"]:find(oldhash,1,true)~=nil,true,"failure_restored_shadow")

-- No result or error may contain either hash.
local function scan(value)
    if type(value)=="string" then
        assert(not value:find(oldhash,1,true) and not value:find(newhash,1,true),
               "credential material leaked")
    elseif type(value)=="table" then
        for k,v in pairs(value) do scan(k);scan(v) end
    end
end
scan(result);scan(restored);scan(why)

same(checks>=12,true,"coverage")
print("AOTT_V3_CREDENTIAL_ACTIVATION_PASS checks="..checks)
