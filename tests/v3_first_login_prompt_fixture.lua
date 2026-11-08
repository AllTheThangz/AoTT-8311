local root=assert(arg[1],"overlay lua root required")
package.path=root.."/?.lua;"..package.path

local ROOT="/ptconf/8311"
local ACK=ROOT.."/.factory-password-prompt-v1.ack"
local files={}
local root_exists=true
local credential="factory"
local open_stage=nil

package.preload["nixio.fs"]=function()
    local M={}
    function M.lstat(path)
        if path==ROOT and root_exists then
            return {type="dir",uid=0,gid=0,modedec=755,dev=1,ino=10}
        end
        local value=files[path]
        if value then
            return {type="reg",uid=0,gid=0,modedec=600,nlink=1,size=#value,dev=1,ino=20}
        end
        return nil
    end
    function M.readfile(path,maximum)
        local value=files[path]
        if not value then return nil end
        if maximum and #value>maximum then return value:sub(1,maximum) end
        return value
    end
    function M.mkdir(path,mode)
        assert(path==ROOT and mode==700)
        root_exists=true
        return true
    end
    function M.rename(source,dest)
        if not files[source] or files[dest] then return false end
        files[dest]=files[source]
        files[source]=nil
        return true
    end
    function M.unlink(path)
        files[path]=nil
        return true
    end
    return M
end

package.preload["nixio"]=function()
    local M={}
    function M.crypt(pass,current)
        assert(pass=="root")
        if credential=="factory" then return current end
        return current.."x"
    end
    function M.getsp(user)
        assert(user=="root")
        return {pwdp="$6$fixture$"..string.rep("A",86)}
    end
    function M.getpid() return 123 end
    function M.open_flags(...) return {...} end
    function M.open(path,flags,mode)
        if path==ROOT then
            return {
                sync=function() return true end,
                close=function() return true end,
            }
        end
        assert(path==ACK..".new.123")
        assert(mode==600)
        assert(files[path]==nil)
        open_stage=path
        return {
            writeall=function(_,data)
                files[path]=data
                return #data
            end,
            sync=function() return true end,
            close=function() return true end,
        }
    end
    return M
end

local first=require "8311.first_login"

local state=first.status()
assert(state.credential_state=="factory_default_root_password")
assert(state.acknowledged==false)
assert(state.prompt_required==true)

local receipt=assert(first.acknowledge())
assert(receipt.status=="factory_prompt_acknowledged")
assert(files[ACK]=="factory-password-prompt-v1\n")
state=first.status()
assert(state.acknowledged==true)
assert(state.prompt_required==false)

receipt=assert(first.acknowledge())
assert(receipt.status=="factory_prompt_already_acknowledged")

files[ACK]=nil
credential="custom"
state=first.status()
assert(state.credential_state=="custom_password_configured")
assert(state.acknowledged==false)
assert(state.prompt_required==false)
receipt=assert(first.acknowledge())
assert(receipt.status=="factory_prompt_not_required")
assert(files[ACK]==nil)

print("AOTT_V3_FIRST_LOGIN_PROMPT_PASS")
