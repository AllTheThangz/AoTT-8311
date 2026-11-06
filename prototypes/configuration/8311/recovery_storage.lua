-- Protected retained-configuration contract used by the native transaction.
-- No filesystem or command access here. Input comes from the checked native
-- storage adapter; output never includes configuration bytes. Source only.
local M={}
local ERROR={}
local MAX_FILE=65536
local RESERVE_BYTES=1048576
local RESERVE_INODES=24
local FIELDS={'previous_network','previous_firewall','candidate_network','candidate_firewall'}
local SOURCE_FIELDS={'previous_network','previous_firewall','previous_environment','previous_cache',
 'candidate_network','candidate_firewall','candidate_environment','candidate_cache'}
local function fields(scope)
 if scope==nil or scope=='uci_only'then return FIELDS end
 if scope=='uci_and_startup_sources'then return SOURCE_FIELDS end
 error('unsupported_retention_scope',0)
end
local function fail(code) error({tag=ERROR,code=code},0) end
local function safe(fn,...)
    local ok,v=pcall(fn,...)
    if ok then return v end
    if type(v)=='table' and rawget(v,'tag')==ERROR then return nil,rawget(v,'code') end
    return nil,'recovery_storage_internal_error'
end
local function plain(t) return type(t)=='table' and getmetatable(t)==nil end
local function int(n,max) return type(n)=='number' and n==math.floor(n) and n>=0 and n<=max end
local function hex(v,n) return type(v)=='string' and #v==n and v:match('^[a-f0-9]+$') end
local function binding(v)
    if not hex(v,16) then fail('retention_binding_invalid') end
end
local function entries(v,scope)
    local selected=fields(scope)
    if not plain(v) then fail('retention_entries_invalid') end
    local count=0
    for k in pairs(v) do
        local valid=false;for _,name in ipairs(selected) do if k==name then valid=true end end
        if not valid then fail('retention_entries_invalid') end
        count=count+1
    end
    if count~=#selected then fail('retention_entries_invalid') end
    for _,name in ipairs(selected) do
        local item=v[name]
        if not plain(item) or not hex(item.sha256,64) or not int(item.bytes,MAX_FILE) or item.bytes==0 then
            fail('retention_entry_invalid')
        end
        for k in pairs(item) do if k~='sha256' and k~='bytes' then fail('retention_entry_invalid') end end
    end
end
function M.reserve(stats)
    return safe(function()
        if not plain(stats) then fail('recovery_capacity_unavailable') end
        local unit=stats.frsize
        if not int(unit,1048576) or unit==0 or not int(stats.bavail,9007199254740991) or
           not int(stats.flag,4294967295) then fail('recovery_capacity_unavailable') end
        if stats.flag%2==1 then fail('recovery_store_read_only') end
        if stats.bavail>math.floor(9007199254740991/unit) then fail('recovery_capacity_unavailable') end
        if stats.bavail*unit<RESERVE_BYTES then fail('recovery_capacity_insufficient') end
        if not int(stats.files,9007199254740991) or not int(stats.favail,9007199254740991) then
            fail('recovery_inode_capacity_unavailable') end
        if stats.files>0 and stats.favail<RESERVE_INODES then fail('recovery_inode_capacity_insufficient') end
        return {status='SOURCE_RECOVERY_CAPACITY_ACCEPTED',reserve_bytes=RESERVE_BYTES,
            reserve_inodes=RESERVE_INODES,inode_accounting_available=stats.files>0,
            physical_durability_unqualified=true}
    end)
end
local function encode(id,v,scope)
    binding(id);entries(v,scope);local selected=fields(scope)
    local rows={scope=='uci_and_startup_sources'and 'AOTT-RETAINED-CONFIG-2'or 'AOTT-RETAINED-CONFIG-1',id}
    for _,name in ipairs(selected) do
        local item=v[name]
        rows[#rows+1]=name..' '..tostring(item.bytes)..' '..item.sha256
    end
    return table.concat(rows,'\n')..'\n'
end
function M.encode(id,v,scope) return safe(encode,id,v,scope) end
local function decode(id,raw,scope)
    binding(id);local selected=fields(scope)
    if type(raw)~='string' or #raw>2048 then fail('retention_manifest_invalid') end
    local rows={};for value in raw:gmatch('([^\n]*)\n') do rows[#rows+1]=value end
    local header=scope=='uci_and_startup_sources'and 'AOTT-RETAINED-CONFIG-2'or 'AOTT-RETAINED-CONFIG-1'
    if #rows~=#selected+2 or rows[1]~=header then fail('retention_manifest_invalid') end
    if rows[2]~=id then fail('retention_manifest_wrong_workspace') end
    local v={}
    for i,name in ipairs(selected) do
        local label,size,hash=rows[i+2]:match('^([a-z_]+) ([0-9]+) ([a-f0-9]+)$')
        if label~=name or not size or #size>5 or not hex(hash,64) then fail('retention_manifest_invalid') end
        v[name]={bytes=tonumber(size),sha256=hash}
    end
    entries(v,scope)
    if encode(id,v,scope)~=raw then fail('retention_manifest_invalid') end
    return v
end
function M.verify(id,raw,actual,scope)
    return safe(function()
        local selected=fields(scope)
        local expected=decode(id,raw,scope);entries(actual,scope)
        for _,name in ipairs(selected) do
            if actual[name].bytes~=expected[name].bytes or actual[name].sha256~=expected[name].sha256 then
                fail('retention_manifest_content_mismatch') end
        end
        return {status='SOURCE_RETAINED_CONFIG_VERIFIED',files=#selected,contains_configuration_values=false,
            authentication_against_privileged_tampering=false,physical_durability_unqualified=true}
    end)
end
-- Proposed production storage is an exact fixed private directory below an
-- independently observed mount. This is an evidence screen, not a writer or
-- permission to install/format a filesystem. Missing evidence is never filled.
function M.screen_persistent_evidence(f)
    return safe(function()
        if not plain(f) or type(f.reference_only)~='boolean' or f.mountpoint~='/ptconf' or f.store_path~='/ptconf/8311/aott-recovery/v1' or
           f.ancestors_verified~=true or f.store_uid~=0 or f.store_gid~=0 or f.store_mode~=700 or
           f.mount_read_only~=false or f.same_filesystem~=true or f.physical_mount_verified~=true then
            fail('persistent_recovery_evidence_incomplete') end
        if f.fs_type~='ubifs' and f.fs_type~='jffs2' then fail('persistent_recovery_filesystem_unqualified') end
        if not f.reference_only and f.live_observation~=true then fail('persistent_recovery_evidence_incomplete') end
        local capacity=M.reserve(f.capacity)
        if not capacity then fail('persistent_recovery_capacity_unqualified') end
        return {status=f.reference_only and 'REFERENCE_STORAGE_SCREEN_ONLY' or 'LIVE_STORAGE_SCREEN_ONLY',
            production_activation_allowed=false,needs_power_loss_and_bank_qualification=true}
    end)
end
return M
