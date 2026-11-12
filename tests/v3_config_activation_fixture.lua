local root=assert(arg[1],"overlay lua root required")
package.path=root.."/?.lua;"..package.path

package.preload["nixio.fs"]=function() return {} end
package.preload["nixio"]=function() return {nanosleep=function()end} end
package.preload["8311.webutil"]=function() return {} end
package.preload["luci.model.uci"]=function() return {cursor=function() return {} end} end

local activation=require "8311.config_activation"
local checks=0
local function same(a,b,label)
    checks=checks+1
    assert(a==b,"CONFIG_ACTIVATION_FIXTURE:"..label..
        " expected="..tostring(b).." got="..tostring(a))
end
local function truth(v,label) same(not not v,true,label) end

local function make_adapter()
    local configured={
        lang="en",hostname="old-onu",timezone="America/New York",
        ntp_servers="old.ntp.example",https_redirect="1",
        pingd="1",ping_ip="192.0.2.10",reverse_arp="1",
        console_en="0",dying_gasp_en="0",rx_los="0",
        ethtool_speed="speed 10000 duplex full autoneg on",
        sfp_vendor="OLDVENDOR",sfp_oui="AA:BB:CC",sfp_partno="OLD-PART",
        sfp_rev="A1",sfp_serial="OLDSERIAL",sfp_date="260101",
        sfp_vendordata="OLD-DATA",
        fix_vlans="1",internet_vlan="0",services_vlan="50",
    }
    local runtime={
        hostname="old-onu",timezone="America/New York",
        ntp_servers="old.ntp.example",https_redirect="1",
        pingd="1",ping_ip="192.0.2.10",reverse_arp="1",
        console_en="0",dying_gasp_en="0",rx_los="0",
        ethtool_speed="speed 10000 duplex full autoneg on",
        sfp_vendor="OLDVENDOR",sfp_oui="AA:BB:CC",sfp_partno="OLD-PART",
        sfp_rev="A1",sfp_serial="OLDSERIAL",sfp_date="260101",
        sfp_vendordata="OLD-DATA",
        fix_vlans="1",internet_vlan="0",services_vlan="50",
    }
    local calls={}
    local fail={}
    local a={}
    function a.read_config(id)
        calls[#calls+1]="read:"..id
        return configured[id]
    end
    function a.set_config(id,value)
        calls[#calls+1]="set:"..id..":"..tostring(value)
        if fail["set:"..id] then return false end
        if fail["rollback_noop:"..id] and value=="old-onu" then
            -- A setter claims success but leaves the new configuration.
            return true
        end
        if id=="timezone" and type(value)=="string" then
            configured[id]=activation.timezone_uci(value)
        else
            configured[id]=value
        end
        if id=="console_en" or id=="dying_gasp_en" or id=="ethtool_speed" then
            runtime[id]=value
        end
        return true
    end
    function a.commit(domain)
        calls[#calls+1]="commit:"..domain
        if fail["commit:"..domain] then return false end
        return true
    end
    function a.reload(service)
        calls[#calls+1]="reload:"..service
        if fail["reload:"..service] then return false end
        if service=="system" then
            runtime.hostname=configured.hostname
            runtime.timezone=configured.timezone
        elseif service=="sysntpd" then
            runtime.ntp_servers=configured.ntp_servers
        elseif service=="uhttpd" then
            runtime.https_redirect=configured.https_redirect
        elseif service=="pingd" then
            runtime.pingd=configured.pingd
            runtime.ping_ip=configured.ping_ip
        elseif service=="rarpd" then
            runtime.reverse_arp=configured.reverse_arp
        elseif service=="rxlos" then
            runtime.rx_los=configured.rx_los
        elseif service=="vlansd" then
            runtime.fix_vlans=configured.fix_vlans
            runtime.internet_vlan=configured.internet_vlan
            runtime.services_vlan=configured.services_vlan
        elseif service=="sfp_eeprom" then
            for _,id in ipairs({"sfp_vendor","sfp_oui","sfp_partno","sfp_rev",
                                "sfp_serial","sfp_date","sfp_vendordata"}) do
                runtime[id]=configured[id]
            end
        end
        return true
    end
    function a.runtime(id,desired)
        calls[#calls+1]="runtime:"..id
        if id=="lang" then return nil,nil,"next_authenticated_luci_request" end
        local injected=fail["runtime:"..id]
        if injected then
            if type(injected)=="number" then
                if injected>0 then
                    fail["runtime:"..id]=injected-1
                    return false,"synthetic-mismatch","fixture_runtime"
                end
            else
                return false,"synthetic-mismatch","fixture_runtime"
            end
        end
        return runtime[id]==(id=="timezone" and activation.timezone_uci(desired) or desired),
               runtime[id],"fixture_runtime"
    end
    function a.wait() calls[#calls+1]="wait" end
    return a,configured,runtime,calls,fail
end

local changes={
    {item={id="lang"},effective="fr"},
    {item={id="hostname"},effective="new-onu"},
    {item={id="timezone"},effective="America/New_York"},
    {item={id="ntp_servers"},effective="time1.example time2.example"},
    {item={id="https_redirect"},effective="0"},
    {item={id="pingd"},effective="0"},
    {item={id="ping_ip"},effective="192.0.2.20"},
    {item={id="reverse_arp"},effective="0"},
    {item={id="console_en"},effective="1"},
    {item={id="dying_gasp_en"},effective="1"},
    {item={id="rx_los"},effective="1"},
    {item={id="ethtool_speed"},effective="speed 10000 duplex full autoneg on"},
    {item={id="sfp_vendor"},effective="NEWVENDOR"},
    {item={id="sfp_oui"},effective="11:22:33"},
    {item={id="sfp_partno"},effective="NEW-PART"},
    {item={id="sfp_rev"},effective="B2"},
    {item={id="sfp_serial"},effective="NEWSERIAL"},
    {item={id="sfp_date"},effective="261107"},
    {item={id="sfp_vendordata"},effective="NEW-DATA"},
    {item={id="fix_vlans"},effective="1"},
    {item={id="internet_vlan"},effective="35"},
    {item={id="services_vlan"},effective="36"},
    {item={id="bootdelay"},effective="3"},
}
local plan=assert(activation.plan(changes))
same(#plan.fields,22,"twentytwo_live_verified_fields")
same(plan.system_reload,true,"system_reload_planned")
same(plan.ntp_reload,true,"ntp_reload_planned")
same(plan.luci_request_reload,true,"luci_request_reload_planned")
same(plan.uhttpd_reload,true,"uhttpd_reload_planned")
same(plan.optic_commit,true,"optic_commit_planned")
same(plan.rxlos_restart,true,"rxlos_restart_planned")
same(plan.vlansd_restart,true,"vlansd_restart_planned")
same(plan.sfp_reload,true,"sfp_reload_planned")
same(activation.timezone_uci("America/New_York"),"America/New York","timezone_uci")
same(activation.timezone_file("America/New York"),
     "/usr/share/zoneinfo/America/New_York","timezone_file")

local a,c,r,calls,fail=make_adapter()
local result=assert(activation.apply(changes,a))
same(result.success,true,"success")
same(result.system_reloaded,true,"system_reloaded")
same(result.ntp_reloaded,true,"ntp_reloaded")
same(result.requires_new_authenticated_request,true,"language_new_request")
for _,id in ipairs({"lang","hostname","timezone","ntp_servers","https_redirect",
    "pingd","ping_ip","reverse_arp","console_en","dying_gasp_en","rx_los","ethtool_speed",
    "sfp_vendor","sfp_oui","sfp_partno","sfp_rev","sfp_serial","sfp_date","sfp_vendordata",
    "fix_vlans","internet_vlan","services_vlan"}) do
    truth(result.fields[id].configured_verified,"configured_"..id)
end
same(result.fields.lang.runtime_effect_proven,false,"lang_not_same_request_proof")
same(result.fields.lang.runtime_pending,true,"lang_pending_new_request")
same(result.fields.hostname.runtime_effect_proven,true,"hostname_runtime")
same(result.fields.timezone.runtime_effect_proven,true,"timezone_runtime")
same(result.fields.ntp_servers.runtime_effect_proven,true,"ntp_runtime")
same(result.fields.https_redirect.runtime_effect_proven,true,"https_redirect_runtime")
same(result.uhttpd_reloaded,true,"uhttpd_reloaded")
same(result.fields.pingd.runtime_effect_proven,true,"pingd_runtime")
same(result.fields.ping_ip.runtime_effect_proven,true,"ping_ip_runtime")
same(result.fields.reverse_arp.runtime_effect_proven,true,"reverse_arp_runtime")
same(result.pingd_restarted,true,"pingd_restarted")
same(result.rarpd_restarted,true,"rarpd_restarted")
same(result.rxlos_restarted,true,"rxlos_restarted")
same(result.vlansd_restarted,true,"vlansd_restarted")
same(result.sfp_eeprom_reloaded,true,"sfp_eeprom_reloaded")
for _,id in ipairs({"console_en","dying_gasp_en","rx_los","ethtool_speed","sfp_vendor","sfp_oui",
                    "sfp_partno","sfp_rev","sfp_serial","sfp_date","sfp_vendordata",
                    "fix_vlans","internet_vlan","services_vlan"}) do
    same(result.fields[id].runtime_effect_proven,true,"runtime_"..id)
end
same(c.lang,"fr","lang_config")
same(c.hostname,"new-onu","hostname_config")
same(c.timezone,"America/New York","timezone_normalized")
same(c.ntp_servers,"time1.example time2.example","ntp_config")
same(c.https_redirect,"0","https_redirect_config")
same(r.https_redirect,"0","https_redirect_runtime_state")
same(c.pingd,"0","pingd_config")
same(c.ping_ip,"192.0.2.20","ping_ip_config")
same(c.reverse_arp,"0","reverse_arp_config")

-- NTP blank disables the active peer set and remains a valid live state.
a,c,r,calls,fail=make_adapter()
local disabled=assert(activation.apply({
    {item={id="ntp_servers"},effective=""}
},a))
same(disabled.success,true,"ntp_disable_success")
same(c.ntp_servers,"","ntp_disabled_config")
same(r.ntp_servers,"","ntp_disabled_runtime")
same(disabled.fields.ntp_servers.runtime_effect_proven,true,"ntp_disable_runtime")

-- Runtime mismatch triggers rollback to the prior configured values.
a,c,r,calls,fail=make_adapter()
fail["runtime:hostname"]=true
local mismatch=assert(activation.apply({
    {item={id="hostname"},effective="new-onu"},
    {item={id="timezone"},effective="UTC"},
},a))
same(mismatch.success,false,"runtime_mismatch_fails")
same(mismatch.error,"runtime_effect_mismatch","runtime_mismatch_reason")
same(mismatch.failed_field,"hostname","runtime_mismatch_field")
same(mismatch.rollback_attempted,true,"runtime_rollback_attempted")
same(mismatch.rollback_succeeded,false,"persistent_runtime_probe_does_not_prove_rollback")
same(mismatch.rollback_configured_verified,true,"configured_rollback_verified")
same(mismatch.rollback_runtime_verified,false,"unverified_runtime_rollback")
same(mismatch.runtime_state_unknown,true,"runtime_state_accurate_unknown")
same(c.hostname,"old-onu","runtime_rollback_hostname")
same(c.timezone,"America/New York","runtime_rollback_timezone")

-- A bounded initial runtime mismatch followed by a genuinely restored
-- consumer proves rollback, unlike a bare successful reload exit code.
a,c,r,calls,fail=make_adapter()
fail["runtime:hostname"]=7
local recovered=assert(activation.apply({
    {item={id="hostname"},effective="new-onu"}
},a))
same(recovered.success,false,"bounded_runtime_mismatch_fails_forward_apply")
same(recovered.error,"runtime_effect_mismatch","bounded_mismatch_reason")
same(recovered.rollback_commands_succeeded,true,"rollback_commands_success")
same(recovered.rollback_configured_verified,true,"rollback_config_readback")
same(recovered.rollback_runtime_verified,true,"rollback_active_consumer")
same(recovered.rollback_succeeded,true,"genuinely_restored_runtime_receipt")
same(c.hostname,"old-onu","restored_hostname_config")
same(r.hostname,"old-onu","restored_hostname_runtime")

-- A setter can lie about restoration. Successful set/commit/reload commands
-- without a matching getter must never be called a verified rollback.
a,c,r,calls,fail=make_adapter()
fail["runtime:hostname"]=true
fail["rollback_noop:hostname"]=true
local lied=assert(activation.apply({
    {item={id="hostname"},effective="new-onu"}
},a))
same(lied.success,false,"stale_restore_remains_failure")
same(lied.rollback_commands_succeeded,true,"lying_setter_commands_report_success")
same(lied.rollback_configured_verified,false,"readback_detects_lying_setter")
same(lied.rollback_succeeded,false,"lying_setter_not_accepted")
same(#lied.rollback_details.configured_mismatch_fields,1,"mismatch_field_reported")
same(lied.rollback_details.configured_mismatch_fields[1],"hostname","mismatch_field_name")
same(c.hostname,"new-onu","stale_configuration_was_not_restored")

-- A commit failure also rolls staged UCI values back.
a,c,r,calls,fail=make_adapter()
fail["commit:system"]=true
local commitfail=assert(activation.apply({
    {item={id="hostname"},effective="new-onu"}
},a))
same(commitfail.success,false,"commit_failure")
same(commitfail.error,"system_commit_failed","commit_failure_reason")
same(commitfail.rollback_attempted,true,"commit_rollback_attempted")
same(c.hostname,"old-onu","commit_rollback_config")

-- Service reload failure is not reported as successful activation.
a,c,r,calls,fail=make_adapter()
fail["reload:sysntpd"]=true
local reloadfail=assert(activation.apply({
    {item={id="ntp_servers"},effective="new.ntp.example"}
},a))
same(reloadfail.success,false,"reload_failure")
same(reloadfail.error,"ntp_reload_failed","reload_failure_reason")
same(reloadfail.rollback_attempted,true,"reload_rollback_attempted")
same(c.ntp_servers,"old.ntp.example","reload_rollback_config")

-- Unsupported fields are deliberately ignored by this activation layer.
a,c,r,calls,fail=make_adapter()
local none=assert(activation.apply({
    {item={id="gpon_sn"},effective="ABCD00000000"}
},a))
same(none.success,true,"unsupported_not_failed")
same(#none.order,0,"unsupported_not_activated")
same(#calls,0,"unsupported_no_runtime_calls")

truth(checks>=80,"coverage")
print("AOTT_V3_CONFIG_ACTIVATION_PASS checks="..checks)
