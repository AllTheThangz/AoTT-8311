-- AoTT-8311 V3 management VLAN and recovery readiness preflight.
-- Read-only: fixed native/UCI reads, no mkdir, UCI mutation, environment setter,
-- service reload, firmware write, boot selector change, or recovery-store write.
local fs=require "nixio.fs"
local web=require "8311.webutil"
local reader=require "8311.native_management_reader"
local storage=require "8311.recovery_storage"
local transition=require "8311.vlan_transition"
local M={}
local STORE="/ptconf/8311/aott-recovery/v1"
local MOUNT="/ptconf"
local PARENT="/ptconf/8311"

local function trusted_dir(st)
    if type(st)~="table" or st.type~="dir" or st.uid~=0 or st.gid~=0 or
       type(st.modedec)~="number" then return false end
    local group_write=math.floor(st.modedec/16)%2==1
    local other_write=math.floor(st.modedec/2)%2==1
    return not group_write and not other_write
end
local function mount_record()
    local raw=fs.readfile("/proc/mounts",65536)
    if type(raw)~="string" then return nil,"mount_table_unavailable" end
    local found
    for line in raw:gmatch("([^\n]+)") do
        local source,target,kind,options=line:match("^(%S+) (%S+) (%S+) (%S+)")
        if target==MOUNT then
            if found then return nil,"ptconf_mount_not_unique" end
            found={source=source,kind=kind,options=options}
        end
    end
    if not found then return nil,"ptconf_mount_unavailable" end
    if found.kind~="ubifs" and found.kind~="jffs2" then
        return nil,"ptconf_filesystem_unqualified"
    end
    local rw,sync=false,false
    for item in found.options:gmatch("[^,]+") do
        if item=="rw" then rw=true elseif item=="sync" then sync=true end
    end
    if not rw then return nil,"ptconf_read_only_or_unknown" end
    return {fs_type=found.kind,rw=true,sync=sync}
end
local function storage_status()
    local mount,why=mount_record()
    if not mount then return nil,why end
    local root,parent=fs.lstat(MOUNT),fs.lstat(PARENT)
    if not trusted_dir(root) or not trusted_dir(parent) then
        return nil,"ptconf_ancestor_permissions_unqualified"
    end
    local stats=fs.statvfs(MOUNT)
    local capacity,capacity_why=storage.reserve(stats)
    if not capacity then return nil,capacity_why end
    local store=fs.lstat(STORE)
    local result={
        status="RECOVERY_STORAGE_PREFLIGHT",
        fs_type=mount.fs_type,
        mount_read_write=mount.rw,
        mount_sync=mount.sync,
        capacity_qualified=true,
        reserve_bytes=capacity.reserve_bytes,
        reserve_inodes=capacity.reserve_inodes,
        store_present=store~=nil,
        store_ready=false,
        provisioning_required=store==nil,
        power_loss_qualified=false,
        bank_compatibility_qualified=false,
        production_write_allowed=false,
    }
    if not store then return result end
    if not trusted_dir(store) or store.modedec~=448 or store.dev~=root.dev then
        return nil,"recovery_store_permissions_unqualified"
    end
    local screened,screen_why=storage.screen_persistent_evidence({
        reference_only=false,live_observation=true,
        mountpoint=MOUNT,store_path=STORE,ancestors_verified=true,
        store_uid=store.uid,store_gid=store.gid,store_mode=store.modedec,
        mount_read_only=false,same_filesystem=true,physical_mount_verified=true,
        fs_type=mount.fs_type,capacity=stats,
    })
    if not screened then return nil,screen_why end
    result.store_ready=true
    result.provisioning_required=false
    result.screen_status=screened.status
    return result
end
local function package(name)
    local code,raw,overflow=web.capture(
        {"/usr/bin/timeout","-k","1","5","/sbin/uci","export",name},65536)
    if code~=0 or overflow or type(raw)~="string" then
        return nil,"management_uci_export_failed_"..name
    end
    return transition.parse_export(raw,name)
end
local function snapshot()
    local network,why=package("network")
    if not network then return nil,why end
    local firewall,fw_why=package("firewall")
    if not firewall then return nil,fw_why end
    return {network=network,firewall=firewall}
end
local function topology(s)
    local vlan=0
    local device=s.network.lct_vlan
    if s.network.mgmt~=nil or device~=nil then
        local raw=device and device.options and device.options.vid
        if type(raw)~="string" or not raw:match("^%d+$") then
            return nil,"management_vlan_topology_unqualified"
        end
        vlan=tonumber(raw)
    end
    local h,why=transition.prepare(s,vlan,"eth0_0_1_lct","lan")
    if not h then return nil,why end
    local summary,summary_why=transition.redacted_summary(h,"production_preview")
    if not summary or summary.operations~=0 then
        return nil,summary_why or "management_current_state_not_stable"
    end
    return vlan
end
local function native_status()
    local h,why=reader.read()
    if not h then return nil,why end
    local summary,summary_why=reader.summary(h)
    if not summary then return nil,summary_why end
    return summary
end

function M.status()
    local store,storage_why=storage_status()
    local native,native_why=native_status()
    local current,current_why=snapshot()
    local vlan,topology_why
    if current then
        vlan,topology_why=topology(current)
    else
        topology_why=current_why
    end
    return {
        schema=1,status="MANAGEMENT_VLAN_RUNTIME_PREFLIGHT",
        storage=store or {status="unavailable",reason=storage_why},
        native=native or {status="unavailable",reason=native_why},
        topology=current and vlan~=nil and
            {status="qualified_for_preview",current_vlan=vlan} or
            {status="unavailable",reason=topology_why},
        preview_available=store~=nil and native~=nil and current~=nil and vlan~=nil,
        production_write_allowed=false,
        recovery_store_write_performed=false,
        uci_write_performed=false,
        native_environment_write_performed=false,
        reboot_performed=false,
    }
end

function M.preview(requested)
    if type(requested)~="string" or not requested:match("^%d+$") or #requested>4 then
        return nil,"Management VLAN must be 0 through 4094"
    end
    local vlan=tonumber(requested)
    if not vlan or vlan>4094 then return nil,"Management VLAN must be 0 through 4094" end
    local store,storage_why=storage_status()
    if not store then return nil,storage_why end
    local native,native_why=native_status()
    if not native then return nil,native_why end
    local current,current_why=snapshot()
    if not current then return nil,current_why end
    local current_vlan,topology_why=topology(current)
    if current_vlan==nil then return nil,topology_why end
    local handle,why=transition.prepare(current,vlan,"eth0_0_1_lct","lan")
    if not handle then return nil,why end
    local plan,plan_why=transition.redacted_summary(handle,"production_preview")
    if not plan then return nil,plan_why end
    return {
        schema=1,status="MANAGEMENT_VLAN_PREVIEW",
        current_vlan=current_vlan,requested_vlan=vlan,
        operations=plan.operations,
        network_operations=plan.network_operations,
        firewall_operations=plan.firewall_operations,
        changes_required=plan.changes_required,
        recovery_store_present=store.store_present,
        recovery_store_ready=store.store_ready,
        recovery_provisioning_required=store.provisioning_required,
        native_fields_checked=native.fields,
        native_present_empty=native.present_empty,
        present_empty_restore_blocker=native.wrapper_cannot_restore_present_empty,
        contains_configuration_values=false,
        production_write_allowed=false,
        requires_separate_apply_authorization=true,
        uci_write_performed=false,
        native_environment_write_performed=false,
        recovery_store_write_performed=false,
    }
end
M.STORE=STORE
return M
