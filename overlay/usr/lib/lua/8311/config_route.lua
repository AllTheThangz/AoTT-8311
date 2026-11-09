-- AoTT-8311 V3 server-owned A-to-Z configuration routing contract.
-- Every rendered setting belongs to exactly one mutation path. A field may not
-- silently fall through to generic environment persistence.
local M={}

local LIVE={
    lang=true,hostname=true,timezone=true,ntp_servers=true,
    https_redirect=true,pingd=true,ping_ip=true,reverse_arp=true,
    console_en=true,dying_gasp_en=true,rx_los=true,ethtool_speed=true,
    sfp_vendor=true,sfp_oui=true,sfp_partno=true,sfp_rev=true,
    sfp_serial=true,sfp_date=true,sfp_vendordata=true,
    fix_vlans=true,internet_vlan=true,services_vlan=true,
}
local MANAGEMENT={
    lct_vlan=true,ipaddr=true,netmask=true,gateway=true,dns_server=true,lct_mac=true,
}
local BOOT={
    bootdelay=true,uart_select=true,failsafe_delay=true,persist_root=true,
}
local CREDENTIAL={root_pwhash=true}
local PON={
    gpon_sn=true,vendor_id=true,equipment_id=true,hw_ver=true,
    cp_hw_ver_sync=true,sw_verA=true,sw_verB=true,fw_match_b64=true,
    fw_match_num=true,override_active=true,override_commit=true,
    pon_mode=true,omcc_version=true,iop_mask=true,reg_id_hex=true,
    loid=true,lpwd=true,mib_file=true,pon_slot=true,iphost_mac=true,
    iphost_hostname=true,iphost_domain=true,
}
local GROUPS={
    live=LIVE,management=MANAGEMENT,boot=BOOT,credential=CREDENTIAL,pon=PON,
}
local ORDER={"live","management","boot","credential","pon"}

function M.route(id)
    if type(id)~="string" then return nil end
    local found
    for _,name in ipairs(ORDER) do
        if GROUPS[name][id] then
            if found then return nil end
            found=name
        end
    end
    return found
end

function M.classify(ids)
    if type(ids)~="table" then return nil,"invalid_configuration_change_set" end
    local routes,seen={},{}
    for _,id in ipairs(ids) do
        if type(id)~="string" or seen[id] then
            return nil,"invalid_configuration_change_set"
        end
        seen[id]=true
        local route=M.route(id)
        if not route then return nil,"unrouted_configuration_field_"..tostring(id) end
        routes[route]=true
    end
    local names={}
    for _,name in ipairs(ORDER) do if routes[name] then names[#names+1]=name end end
    if #names==0 then return {route="none",routes={},fields=0} end
    if #names>1 then
        return {
            route="mixed",routes=names,fields=#ids,
            split_required=true,
        }
    end
    return {route=names[1],routes=names,fields=#ids,split_required=false}
end

function M.inventory()
    local out={}
    for _,name in ipairs(ORDER) do
        for id in pairs(GROUPS[name]) do out[id]=name end
    end
    return out
end

M.groups=GROUPS
M.order=ORDER
return M
