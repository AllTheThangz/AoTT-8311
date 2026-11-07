local vendor=assert(arg[1],"vendor root required")
local overlay=assert(arg[2],"overlay root required")
local root=assert(arg[3],"fixture root required")
local mode=assert(arg[4],"mode required")
package.path=overlay.."/?.lua;"..vendor.."/usr/lib/lua/?.lua;"..
    vendor.."/usr/lib/lua/?/init.lua;"..package.path
package.cpath=vendor.."/usr/lib/lua/?.so;"..package.cpath

local nixio=require "nixio"
local fs=require "nixio.fs"
local activation=require "8311.tls_activation"
local persist=root.."/ptconf/8311/uhttpd"
local candidate=root.."/tmp/aott-tls-candidate"
local job=root.."/job"
local fingerprint=string.rep("a",64)

local function write(path,data,mode_value)
    local fd=assert(nixio.open(path,nixio.open_flags("wronly","creat","excl"),mode_value))
    assert(fd:writeall(data)==#data)
    assert(fd:sync()==true)
    assert(fd:close())
end
local function read(path)
    return fs.readfile(path,16384)
end
local original_cert="ORIGINAL-CERTIFICATE\n"
local original_key="ORIGINAL-PRIVATE-KEY\n"
local candidate_cert="CANDIDATE-CERTIFICATE\n"
local candidate_key="CANDIDATE-PRIVATE-KEY\n"
write(persist.."/uhttpd.crt",original_cert,644)
write(persist.."/uhttpd.key",original_key,600)
write(candidate.."/candidate.crt.der",candidate_cert,644)
write(candidate.."/candidate.key.der",candidate_key,600)

local restarts=0
local sleep_calls=0
local provider={}
function provider.digest(path)
    assert(path==candidate.."/candidate.crt.der")
    return fingerprint
end
function provider.recovery_ready()
    return mode~="no_recovery"
end
function provider.restart()
    restarts=restarts+1
    if mode=="restart_fail" and restarts==1 then return false end
    return true
end
function provider.sleep()
    sleep_calls=sleep_calls+1
    if mode=="confirm" and sleep_calls==1 then
        write(job.."/tls-confirm","AOTT-TLS-CONFIRM-1\n",600)
    elseif mode=="crash" then
        error("synthetic_process_death")
    end
end

if mode=="confirm" then
    local result=assert(activation.fixture_activate(root,job,fingerprint,provider,3))
    assert(result.status=="confirmed")
    assert(read(persist.."/uhttpd.crt")==candidate_cert)
    assert(read(persist.."/uhttpd.key")==candidate_key)
    assert(not fs.lstat(persist.."/.aott-tls-pending"))
    assert(not fs.lstat(persist.."/.aott-prev.crt"))
    assert(not fs.lstat(persist.."/.aott-prev.key"))
    assert(restarts==1)
    print("AOTT_TLS_ACTIVATION_CONFIRM_PASS")
elseif mode=="timeout" then
    local result=assert(activation.fixture_activate(root,job,fingerprint,provider,2))
    assert(result.status=="rolled_back" and result.rollback_verified==true)
    assert(read(persist.."/uhttpd.crt")==original_cert)
    assert(read(persist.."/uhttpd.key")==original_key)
    assert(restarts==2)
    print("AOTT_TLS_ACTIVATION_TIMEOUT_ROLLBACK_PASS")
elseif mode=="restart_fail" then
    local result=assert(activation.fixture_activate(root,job,fingerprint,provider,2))
    assert(result.status=="rolled_back" and result.rollback_verified==true)
    assert(read(persist.."/uhttpd.crt")==original_cert)
    assert(read(persist.."/uhttpd.key")==original_key)
    assert(restarts==2)
    print("AOTT_TLS_ACTIVATION_RESTART_ROLLBACK_PASS")
elseif mode=="no_recovery" then
    local result,why=activation.fixture_activate(root,job,fingerprint,provider,1)
    assert(result==nil and why=="tls_secondary_recovery_unavailable")
    assert(read(persist.."/uhttpd.crt")==original_cert)
    assert(read(persist.."/uhttpd.key")==original_key)
    assert(not fs.lstat(persist.."/.aott-tls-pending"))
    assert(restarts==0)
    print("AOTT_TLS_ACTIVATION_RECOVERY_GATE_PASS")
elseif mode=="crash" then
    local ok=pcall(activation.fixture_activate,root,job,fingerprint,provider,2)
    assert(ok==false)
    assert(read(persist.."/uhttpd.crt")==candidate_cert)
    assert(fs.lstat(persist.."/.aott-tls-pending"))
    assert(fs.lstat(persist.."/.aott-prev.crt"))
    assert(fs.lstat(persist.."/.aott-prev.key"))
    local recovery_provider={
        digest=provider.digest,recovery_ready=function()return true end,
        restart=function()error("boot recovery must not restart uhttpd")end,
        sleep=function()end,
    }
    local recovered=assert(activation.fixture_recover(root,recovery_provider))
    assert(recovered.status=="rolled_back")
    assert(read(persist.."/uhttpd.crt")==original_cert)
    assert(read(persist.."/uhttpd.key")==original_key)
    assert(not fs.lstat(persist.."/.aott-tls-pending"))
    print("AOTT_TLS_ACTIVATION_BOOT_RECOVERY_PASS")
else
    error("unknown mode")
end
