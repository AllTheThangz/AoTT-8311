-- AoTT-8311 V3 live activation and runtime verification for lower-risk settings.
-- Only fields with traced native OpenWrt consumers are handled here.
local fs=require "nixio.fs"
local nixio=require "nixio"
local web=require "8311.webutil"
local uci_lib=require "luci.model.uci"
local http_probe=require "8311.local_http_probe"
local daemon_state=require "8311.daemon_state"
local advanced=require "8311.advanced_runtime"
local sfp_runtime=require "8311.sfp_runtime"
local vlan_runtime=require "8311.vlan_runtime"

local M={}
local ORDER={"lang","hostname","timezone","ntp_servers","https_redirect","pingd","ping_ip","reverse_arp",
    "console_en","dying_gasp_en","rx_los","ethtool_speed",
    "sfp_vendor","sfp_oui","sfp_partno","sfp_rev","sfp_serial","sfp_date","sfp_vendordata",
    "fix_vlans","internet_vlan","services_vlan"}
local SAFE={lang=true,hostname=true,timezone=true,ntp_servers=true,https_redirect=true,pingd=true,ping_ip=true,reverse_arp=true,
    console_en=true,dying_gasp_en=true,rx_los=true,ethtool_speed=true,
    sfp_vendor=true,sfp_oui=true,sfp_partno=true,sfp_rev=true,sfp_serial=true,sfp_date=true,sfp_vendordata=true,
    fix_vlans=true,internet_vlan=true,services_vlan=true}
local SFP={sfp_vendor=true,sfp_oui=true,sfp_partno=true,sfp_rev=true,sfp_serial=true,sfp_date=true,sfp_vendordata=true}
local PING_CACHE="/tmp/8311-ping-host"

local function split_words(value)
    local out={}
    if type(value)~="string" then return out end
    for word in value:gmatch("%S+") do out[#out+1]=word end
    return out
end

local function timezone_uci(value)
    if type(value)~="string" then return value end
    return (value:gsub("_"," "))
end

local function timezone_file(value)
    if type(value)~="string" then return nil end
    return "/usr/share/zoneinfo/"..value:gsub(" ","_")
end

local function ping_cache_read()
    local st=fs.lstat(PING_CACHE)
    if not st then return nil,true end
    if st.type~="reg" or st.uid~=0 or st.nlink~=1 or
       type(st.size)~="number" or st.size>96 then
        return nil,false
    end
    local value=fs.readfile(PING_CACHE,97)
    if type(value)~="string" or #value>96 then return nil,false end
    value=value:gsub("[\r\n]+$","")
    if not http_probe.valid_ipv4(value) then return nil,false end
    return value,true
end

local function ping_cache_write(value)
    local current,good=ping_cache_read()
    if not good then return false end
    if value==nil then
        if current==nil then return true end
        return fs.unlink(PING_CACHE)==true
    end
    if not http_probe.valid_ipv4(value) then return false end
    local stage=PING_CACHE..".new."..tostring(nixio.getpid())
    if fs.lstat(stage) then return false end
    local fd=nixio.open(stage,nixio.open_flags("wronly","creat","excl"),600)
    if not fd then return false end
    local data=value.."\n"
    local wrote=fd:writeall(data)
    local closed=fd:close()
    if wrote~=#data or not closed then
        fs.unlink(stage)
        return false
    end
    if fs.rename(stage,PING_CACHE)~=true then
        fs.unlink(stage)
        return false
    end
    local check,verified=ping_cache_read()
    return verified and check==value
end

local function same_words(expected,actual)
    if type(actual)~="table" then return false end
    local seen={}
    for _,word in ipairs(actual) do seen[word]=(seen[word] or 0)+1 end
    for _,word in ipairs(split_words(expected)) do
        if not seen[word] or seen[word]<1 then return false end
        seen[word]=seen[word]-1
    end
    -- sysntpd may also add DHCP-provided peers. The configured peer set must
    -- be present, but additional native peers are not a failed activation.
    return true
end

local function build_plan(changes)
    local desired,previous={},{}
    if type(changes)~="table" then return nil,"invalid_activation_changes" end
    for _,change in ipairs(changes) do
        local item=change and change.item
        local id=item and item.id
        if SAFE[id] then
            if type(change.effective)~="string" then
                return nil,"missing_effective_value_"..id
            end
            desired[id]=change.effective
            if type(change.previous_effective)=="string" then
                previous[id]=change.previous_effective
            end
        end
    end
    local fields={}
    for _,id in ipairs(ORDER) do
        if desired[id]~=nil then fields[#fields+1]=id end
    end
    return {
        fields=fields,
        desired=desired,previous=previous,
        system_reload=desired.hostname~=nil or desired.timezone~=nil,
        ntp_reload=desired.ntp_servers~=nil,
        uhttpd_reload=desired.https_redirect~=nil,
        pingd_restart=desired.pingd~=nil or desired.ping_ip~=nil,
        rarpd_restart=desired.reverse_arp~=nil,
        rxlos_restart=desired.rx_los~=nil,
        vlansd_restart=desired.fix_vlans~=nil or desired.internet_vlan~=nil or desired.services_vlan~=nil,
        env_daemon_restart=desired.pingd~=nil or desired.ping_ip~=nil or desired.reverse_arp~=nil or desired.rx_los~=nil or desired.fix_vlans~=nil or desired.internet_vlan~=nil or desired.services_vlan~=nil,
        optic_commit=desired.dying_gasp_en~=nil,
        sfp_reload=desired.sfp_vendor~=nil or desired.sfp_oui~=nil or desired.sfp_partno~=nil or
            desired.sfp_rev~=nil or desired.sfp_serial~=nil or desired.sfp_date~=nil or desired.sfp_vendordata~=nil,
        luci_request_reload=desired.lang~=nil,
    }
end
M.plan=build_plan

local function live_adapter(plan)
    local uci=uci_lib.cursor()
    local system_section=uci:get_first("system","system")
    local ntp_section=uci:get_first("system","timeserver")
    if plan.system_reload and
       (type(system_section)~="string" or system_section=="") then
        return nil,"system_uci_section_unavailable"
    end
    if plan.ntp_reload and
       (type(ntp_section)~="string" or ntp_section=="") then
        return nil,"ntp_uci_section_unavailable"
    end
    local management_ip=uci:get("network","mgmt","ipaddr")
    if not http_probe.valid_ipv4(management_ip) then
        management_ip=uci:get("network","lct","ipaddr")
    end
    if plan.uhttpd_reload and not http_probe.valid_ipv4(management_ip) then
        return nil,"management_ipv4_unavailable_for_http_verification"
    end

    local A={}

    local function env_value(id)
        local allowed={console_en=true,dying_gasp_en=true,rx_los=true,ethtool_speed=true,
            fix_vlans=true,internet_vlan=true,services_vlan=true}
        if not allowed[id] then return nil end
        local code,out,overflow=web.capture({"/usr/sbin/fwenv_get","--8311",id},256)
        if code~=0 or overflow or type(out)~="string" then return nil end
        out=out:gsub("[\r\n]+$","")
        if #out>128 or out:find("[%z\1-\31\127]") then return nil end
        return out
    end

    function A.read_config(id)
        if id=="lang" then
            return uci:get("luci","main","lang") or "auto"
        elseif id=="hostname" then
            return uci:get("system",system_section,"hostname") or ""
        elseif id=="timezone" then
            return uci:get("system",system_section,"zonename") or ""
        elseif id=="ntp_servers" then
            local values=uci:get_list("system",ntp_section,"server")
            local out={}
            for _,value in ipairs(values or {}) do
                if type(value)=="string" and value~="" then out[#out+1]=value end
            end
            return table.concat(out," ")
        elseif id=="https_redirect" then
            return uci:get("uhttpd","main","redirect_https") or "0"
        elseif id=="pingd" then
            local state=daemon_state.read("pingd")
            return state and (state.enabled and "1" or "0") or nil
        elseif id=="ping_ip" then
            local state=daemon_state.read("pingd")
            if state and state.target then return state.target end
            local value,good=ping_cache_read()
            return good and value or nil
        elseif id=="reverse_arp" then
            local state=daemon_state.read("rarpd")
            return state and (state.enabled and "1" or "0") or nil
        elseif id=="console_en" or id=="dying_gasp_en" or id=="rx_los" or id=="ethtool_speed" or
               id=="fix_vlans" or id=="internet_vlan" or id=="services_vlan" then
            return env_value(id) or ""
        elseif SFP[id] then
            local option=sfp_runtime.option(id)
            return option and (uci:get("sfp_eeprom","default",option) or "") or nil
        end
    end

    function A.rollback_value(id)
        if id=="console_en" then
            return advanced.console()
        elseif id=="dying_gasp_en" then
            return advanced.dying()
        elseif id=="ethtool_speed" then
            local state=advanced.current_ethtool()
            return state and advanced.canonical_ethtool(state) or nil
        end
        return A.read_config(id)
    end

    function A.set_config(id,value)
        if id=="lang" then
            return uci:set("luci","main","lang",value=="" and "auto" or value)
        elseif id=="hostname" then
            if value==nil then return uci:delete("system",system_section,"hostname") end
            return uci:set("system",system_section,"hostname",value)
        elseif id=="timezone" then
            if value==nil then return uci:delete("system",system_section,"zonename") end
            return uci:set("system",system_section,"zonename",timezone_uci(value))
        elseif id=="ntp_servers" then
            local words=split_words(value or "")
            local ok=uci:set_list("system",ntp_section,"server",words)
            if not ok then return false end
            return uci:set("system",ntp_section,"enabled",#words>0 and "1" or "0")
        elseif id=="https_redirect" then
            if value==nil then return uci:delete("uhttpd","main","redirect_https") end
            if value~="0" and value~="1" then return false end
            return uci:set("uhttpd","main","redirect_https",value)
        elseif id=="pingd" then
            return value=="0" or value=="1"
        elseif id=="ping_ip" then
            return ping_cache_write(value)
        elseif id=="reverse_arp" then
            return value=="0" or value=="1"
        elseif id=="console_en" then
            local applied=advanced.apply_console(value)
            return applied~=nil
        elseif id=="dying_gasp_en" then
            if value~="0" and value~="1" then return false end
            if uci:set("optic","common","dg_dis",value=="1" and "0" or "1")~=true then
                return false
            end
            local applied=advanced.apply_dying(value)
            return applied~=nil
        elseif id=="rx_los" then
            return value=="0" or value=="1"
        elseif id=="fix_vlans" then
            return value=="0" or value=="1" or value=="2"
        elseif id=="internet_vlan" then
            return value=="" or (value:match("^%d+$")~=nil and tonumber(value)<=4095)
        elseif id=="services_vlan" then
            return value=="" or (value:match("^%d+$")~=nil and tonumber(value)>=1 and tonumber(value)<=4095)
        elseif id=="ethtool_speed" then
            if value=="" then return true end
            local applied=advanced.apply_ethtool(value)
            return applied~=nil
        elseif SFP[id] then
            local option=sfp_runtime.option(id)
            if not option then return false end
            if value=="" then
                local current=uci:get("sfp_eeprom","default",option)
                return current==nil or uci:delete("sfp_eeprom","default",option)==true
            end
            return uci:set("sfp_eeprom","default",option,value)==true
        end
        return false
    end

    function A.commit(domain)
        return uci:commit(domain)
    end

    function A.reload(service)
        local path=service=="system" and "/etc/init.d/system"
            or service=="sysntpd" and "/etc/init.d/sysntpd"
            or service=="uhttpd" and "/etc/init.d/uhttpd"
            or service=="pingd" and "/etc/init.d/8311-pingd"
            or service=="rarpd" and "/etc/init.d/8311-rarpd"
            or service=="rxlos" and "/etc/init.d/8311-rx-los"
            or service=="vlansd" and "/etc/init.d/8311-vlansd"
            or service=="sfp_eeprom" and "/etc/init.d/sfp_eeprom.sh" or nil
        if not path then return false,"unsupported_reload_service" end
        if service=="sfp_eeprom" then
            local code,_,overflow=web.capture({path,"stop"},4096)
            if code~=0 or overflow then return false end
            code,_,overflow=web.capture({path,"boot"},4096)
            return code==0 and not overflow
        end
        local action=(service=="pingd" or service=="rarpd" or service=="rxlos" or service=="vlansd") and "restart" or "reload"
        local code,_,overflow=web.capture({path,action},4096)
        return code==0 and not overflow
    end

    local function pid_list()
        local code,out,overflow=web.capture({"/bin/pidof","ntpd"},512)
        if code~=0 or overflow or type(out)~="string" then return {} end
        local pids={}
        for pid in out:gmatch("%d+") do pids[#pids+1]=pid end
        return pids
    end

    local function ntp_peers()
        local peers={}
        for _,pid in ipairs(pid_list()) do
            local raw=fs.readfile("/proc/"..pid.."/cmdline",8192)
            if type(raw)=="string" and raw:find("^/usr/sbin/ntpd%z") then
                local argv={}
                for part in raw:gmatch("([^%z]+)") do argv[#argv+1]=part end
                local i=1
                while i<=#argv do
                    if argv[i]=="-p" and type(argv[i+1])=="string" then
                        peers[#peers+1]=argv[i+1]
                        i=i+2
                    else
                        i=i+1
                    end
                end
            end
        end
        return peers
    end

    function A.runtime(id,desired)
        if id=="lang" then
            return nil,nil,"next_authenticated_luci_request"
        elseif id=="hostname" then
            local value=fs.readfile("/proc/sys/kernel/hostname",128)
            if type(value)~="string" then return false,nil,"kernel_proc_hostname" end
            value=value:gsub("[\r\n]+$","")
            return value==desired,value,"kernel_proc_hostname"
        elseif id=="timezone" then
            local link=fs.readlink("/tmp/localtime")
            local expected=timezone_file(desired)
            return link==expected,link,"tmp_localtime_symlink"
        elseif id=="ntp_servers" then
            local peers=ntp_peers()
            local expected=split_words(desired)
            if #expected==0 then
                return #peers==0,table.concat(peers," "),"active_ntpd_process_arguments"
            end
            return same_words(desired,peers),table.concat(peers," "),"active_ntpd_process_arguments"
        elseif id=="https_redirect" then
            local observed,why=http_probe.inspect(management_ip)
            if not observed then
                return false,nil,"local_http_response:"..tostring(why)
            end
            local active=observed.redirects_https and "1" or "0"
            return active==desired,active,
                "local_http_response_status_"..tostring(observed.status)
        elseif id=="pingd" then
            local state,why=daemon_state.read("pingd")
            if not state then return false,nil,"pingd_runtime_state:"..tostring(why) end
            local value=state.enabled and "1" or "0"
            return value==desired,value,
                state.active and "pingd_runtime_enabled_active" or "pingd_runtime_enabled_idle"
        elseif id=="ping_ip" then
            local state,why=daemon_state.read("pingd")
            if not state then return false,nil,"pingd_runtime_state:"..tostring(why) end
            return state.target==desired,state.target,"pingd_runtime_target"
        elseif id=="reverse_arp" then
            local state,why=daemon_state.read("rarpd")
            if not state then return false,nil,"rarpd_runtime_state:"..tostring(why) end
            local value=state.enabled and "1" or "0"
            return value==desired,value,
                state.active and "rarpd_runtime_enabled_active" or "rarpd_runtime_enabled_idle"
        elseif id=="console_en" then
            local value,why=advanced.console()
            if value==nil then return false,nil,"console_gpio:"..tostring(why) end
            return value==desired,value,"kernel_gpio510_output"
        elseif id=="dying_gasp_en" then
            local value,why=advanced.dying()
            if value==nil then return false,nil,"dying_gasp_gpio:"..tostring(why) end
            local configured=uci:get("optic","common","dg_dis")
            local expected=desired=="1" and "0" or "1"
            if configured~=expected then return false,value,"optic_common_dg_dis_mismatch" end
            return value==desired,value,"kernel_gpio508_and_optic_config"
        elseif id=="rx_los" then
            local state,why=daemon_state.read("rxlos")
            if not state then return false,nil,"rxlos_runtime_state:"..tostring(why) end
            local value=state.enabled and "1" or "0"
            return value==desired,value,
                state.active and "rxlos_runtime_monitoring" or "rxlos_runtime_forced_low"
        elseif id=="fix_vlans" or id=="internet_vlan" or id=="services_vlan" then
            return vlan_runtime.matches(id,desired)
        elseif id=="ethtool_speed" then
            if desired=="" then return nil,nil,"ethtool_clear_requires_reboot" end
            return advanced.ethtool_matches(desired)
        elseif SFP[id] then
            return sfp_runtime.matches(id,desired)
        end
        return nil,nil,"unsupported_runtime_probe"
    end

    function A.wait()
        nixio.nanosleep(0,150000000)
    end

    return A
end

-- Native rollback is not considered successful merely because UCI setters,
-- commit/reload commands or daemon restarts returned true. Verify BOTH the
-- configured getter and the active consumer, and expose unknown/pending state
-- without returning source values or secrets to the caller.
local function rollback(adapter,prior,plan)
    local receipt={
        commands_succeeded=true,configured_verified=true,runtime_verified=true,
        configured_mismatch_fields={},runtime_unverified_fields={},
        succeeded=false,
    }
    local function command(fn,...)
        local ran,result=pcall(fn,...)
        if not ran or result~=true then receipt.commands_succeeded=false end
    end
    for _,id in ipairs(plan.fields) do
        command(adapter.set_config,id,prior[id])
    end
    if plan.desired.lang~=nil then command(adapter.commit,"luci") end
    if plan.system_reload or plan.ntp_reload then command(adapter.commit,"system") end
    if plan.uhttpd_reload then command(adapter.commit,"uhttpd") end
    if plan.optic_commit then command(adapter.commit,"optic") end
    if plan.sfp_reload then command(adapter.commit,"sfp_eeprom") end
    if plan.system_reload then command(adapter.reload,"system") end
    if plan.ntp_reload then command(adapter.reload,"sysntpd") end
    if plan.uhttpd_reload then command(adapter.reload,"uhttpd") end
    if plan.pingd_restart then command(adapter.reload,"pingd") end
    if plan.rarpd_restart then command(adapter.reload,"rarpd") end
    if plan.rxlos_restart then command(adapter.reload,"rxlos") end
    if plan.vlansd_restart then command(adapter.reload,"vlansd") end
    if plan.sfp_reload then command(adapter.reload,"sfp_eeprom") end

    for _,id in ipairs(plan.fields) do
        local value=prior[id]
        local expected=id=="timezone" and timezone_uci(value) or value
        if id=="lang" and expected=="" then expected="auto" end
        local fetched,configured=pcall(adapter.read_config,id)
        -- nil is also returned when a probe fails. Without a known
        -- previous value, we cannot distinguish deletion from failure.
        if value==nil or not fetched or configured~=expected then
            receipt.configured_verified=false
            receipt.configured_mismatch_fields[#receipt.configured_mismatch_fields+1]=id
        end
        local verified=false
        if type(value)=="string" then
            for attempt=1,7 do
                local ran,active=pcall(adapter.runtime,id,value)
                if ran and active==true then
                    verified=true
                    break
                end
                -- nil denotes next-request/reboot-pending or unavailable,
                -- not an independently verified runtime effect.
                if not ran or active==nil then break end
                if attempt<7 then
                    local waited=pcall(adapter.wait)
                    if not waited then break end
                end
            end
        end
        if not verified then
            receipt.runtime_verified=false
            receipt.runtime_unverified_fields[#receipt.runtime_unverified_fields+1]=id
        end
    end
    -- Boot-environment controlled daemons cannot be replayed from this
    -- UCI-only rollback function. Their effect remains unverified.
    if plan.env_daemon_restart then receipt.runtime_verified=false end
    receipt.succeeded=receipt.commands_succeeded and receipt.configured_verified and
        receipt.runtime_verified
    return receipt
end

function M.apply(changes,adapter)
    local plan,why=build_plan(changes)
    if not plan then return nil,why end
    local result={
        schema=1,success=true,fields={},order=plan.fields,
        system_reloaded=false,ntp_reloaded=false,
        requires_new_authenticated_request=plan.luci_request_reload,
        rollback_attempted=false,rollback_succeeded=nil,
    }
    if #plan.fields==0 then return result end
    if adapter==nil then
        adapter,why=live_adapter(plan)
        if not adapter then return nil,why end
    end
    local required={"read_config","set_config","commit","reload","runtime","wait"}
    for _,name in ipairs(required) do
        if type(adapter[name])~="function" then return nil,"invalid_activation_adapter" end
    end

    local prior={}
    local rollback_prior={}
    for _,id in ipairs(plan.fields) do
        prior[id]=adapter.read_config(id)
        if prior[id]==nil then prior[id]=plan.previous[id] end
        rollback_prior[id]=type(adapter.rollback_value)=="function" and adapter.rollback_value(id) or prior[id]
        if rollback_prior[id]==nil then rollback_prior[id]=prior[id] end
        result.fields[id]={
            id=id,desired=plan.desired[id],previous_configured=prior[id],
            configured_verified=false,runtime_effect_proven=false,
            runtime_pending=false,observed_runtime=nil,observed_source=nil,
        }
    end

    local function fail(reason,id)
        result.success=false
        result.error=reason
        result.failed_field=id
        result.rollback_attempted=true
        local restored=rollback(adapter,rollback_prior,plan)
        result.rollback_succeeded=restored.succeeded
        result.rollback_commands_succeeded=restored.commands_succeeded
        result.rollback_configured_verified=restored.configured_verified
        result.rollback_runtime_verified=restored.runtime_verified
        result.rollback_details=restored
        result.runtime_state_unknown=not restored.runtime_verified
        return result
    end

    for _,id in ipairs(plan.fields) do
        if adapter.set_config(id,plan.desired[id])~=true then
            return fail("uci_stage_failed",id)
        end
    end
    if plan.desired.lang~=nil and adapter.commit("luci")~=true then
        return fail("luci_commit_failed","lang")
    end
    if (plan.system_reload or plan.ntp_reload) and adapter.commit("system")~=true then
        return fail("system_commit_failed",plan.desired.hostname and "hostname" or
                    plan.desired.timezone and "timezone" or "ntp_servers")
    end
    if plan.uhttpd_reload and adapter.commit("uhttpd")~=true then
        return fail("uhttpd_commit_failed","https_redirect")
    end
    if plan.optic_commit and adapter.commit("optic")~=true then
        return fail("optic_commit_failed","dying_gasp_en")
    end
    if plan.sfp_reload and adapter.commit("sfp_eeprom")~=true then
        return fail("sfp_eeprom_commit_failed","sfp_vendor")
    end
    if plan.system_reload then
        if adapter.reload("system")~=true then return fail("system_reload_failed","hostname") end
        result.system_reloaded=true
    end
    if plan.ntp_reload then
        if adapter.reload("sysntpd")~=true then return fail("ntp_reload_failed","ntp_servers") end
        result.ntp_reloaded=true
    end
    if plan.uhttpd_reload then
        if adapter.reload("uhttpd")~=true then
            return fail("uhttpd_reload_failed","https_redirect")
        end
        result.uhttpd_reloaded=true
    end
    if plan.pingd_restart then
        if adapter.reload("pingd")~=true then
            return fail("pingd_restart_failed",plan.desired.pingd and "pingd" or "ping_ip")
        end
        result.pingd_restarted=true
    end
    if plan.rarpd_restart then
        if adapter.reload("rarpd")~=true then
            return fail("rarpd_restart_failed","reverse_arp")
        end
        result.rarpd_restarted=true
    end
    if plan.rxlos_restart then
        if adapter.reload("rxlos")~=true then
            return fail("rxlos_restart_failed","rx_los")
        end
        result.rxlos_restarted=true
    end
    if plan.vlansd_restart then
        if adapter.reload("vlansd")~=true then
            return fail("vlansd_restart_failed","fix_vlans")
        end
        result.vlansd_restarted=true
    end
    if plan.sfp_reload then
        if adapter.reload("sfp_eeprom")~=true then
            return fail("sfp_eeprom_reload_failed","sfp_vendor")
        end
        result.sfp_eeprom_reloaded=true
    end
    -- Native service reload/restart completion and procd child publication
    -- are asynchronous. Bound verification to six 150 ms waits per field
    -- instead of treating one scheduler delay as a failed activation.
    for _,id in ipairs(plan.fields) do
        local expected=plan.desired[id]
        local compare_expected=id=="timezone" and timezone_uci(expected) or expected
        if id=="lang" and compare_expected=="" then compare_expected="auto" end
        local configured,runtime_ok,observed,source
        local configured_match=false
        for attempt=1,7 do
            configured=adapter.read_config(id)
            configured_match=configured==compare_expected
            if configured_match then
                runtime_ok,observed,source=adapter.runtime(id,expected)
                if runtime_ok==true or runtime_ok==nil then break end
            end
            if attempt<7 then adapter.wait() end
        end
        local field=result.fields[id]
        field.configured_value=configured
        if not configured_match then
            return fail("configured_readback_mismatch",id)
        end
        field.configured_verified=true
        field.observed_runtime=observed
        field.observed_source=source
        if runtime_ok==true then
            field.runtime_effect_proven=true
        elseif runtime_ok==nil then
            field.runtime_pending=true
        else
            return fail("runtime_effect_mismatch",id)
        end
    end
    return result
end

M.safe_fields=SAFE
M.timezone_uci=timezone_uci
M.timezone_file=timezone_file
return M
