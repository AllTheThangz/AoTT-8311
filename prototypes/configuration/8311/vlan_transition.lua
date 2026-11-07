-- C-014 native Lua 5.1 transition core. SOURCE ONLY, not installed.
-- No filesystem, shell, ubus, network or device access. Private plan handles
-- hold sensitive snapshots; only fixed-code, redacted receipts leave execute.
local M={}
local OWNER="aott_c014_v1"
local plans=setmetatable({}, {__mode="k"})
local ADDRESS={"ipaddr","netmask","gateway","dns"}
local LCT={ipaddr=true,netmask=true,gateway=true,dns=true,ifname=true,
           proto=true,auto=true,macaddr=true}
local DEVICE={aott_owner=true,ifname=true,name=true,type=true,vid=true}
local ERROR_TAG={}
local function deny(code) error({tag=ERROR_TAG,code=code},0) end
local function plain(t) return type(t)=="table" and getmetatable(t)==nil end
local function ident(s)
    return type(s)=="string" and #s>=1 and #s<=48 and s:match("^[A-Za-z0-9_]+$")
end
local function text(s)
    return type(s)=="string" and #s<=2048 and not s:find("[%z\1-\31\127]")
end
local function keys(t)
    local r={};for k in pairs(t) do r[#r+1]=k end;table.sort(r);return r
end
local function list(t)
    if not plain(t) then deny("invalid_option_list") end
    local n=0;for k,v in pairs(t) do
        if type(k)~="number" or k~=math.floor(k) or k<1 or k>64 or not text(v) then
            deny("invalid_option_list")
        end
        n=n+1
    end
    if n==0 or n>64 then deny("invalid_option_list") end
    for i=1,n do if t[i]==nil then deny("sparse_option_list") end end
    return n
end
local function copy(t)
    if type(t)~="table" then return t end
    local r={};for k,v in pairs(t) do r[k]=copy(v) end;return r
end
local function equal(a,b)
    if type(a)~=type(b) then return false end
    if type(a)~="table" then return a==b end
    for k,v in pairs(a) do if not equal(v,b[k]) then return false end end
    for k in pairs(b) do if a[k]==nil then return false end end
    return true
end
local function bounded_snapshot(s)
    if not plain(s) or not plain(s.network) or not plain(s.firewall) then
        deny("snapshot_packages_invalid")
    end
    for k in pairs(s) do if k~="network" and k~="firewall" then deny("snapshot_packages_invalid") end end
    local bytes=0
    for _,pkg in ipairs({"network","firewall"}) do
        local count=0
        for name,section in pairs(s[pkg]) do
            count=count+1
            local anonymous=type(name)=="string" and name:match("^@[A-Za-z0-9_]+%[%d+%]$")
            if (not ident(name) and not anonymous) or #name>64 or count>128 or
               not plain(section) or not ident(section.type) or not plain(section.options) then
                deny("invalid_snapshot_section")
            end
            for k in pairs(section) do
                if k~="type" and k~="options" then deny("invalid_snapshot_section") end
            end
            local options=0
            bytes=bytes+#name+#section.type
            for k,v in pairs(section.options) do
                options=options+1
                if not ident(k) or options>128 then deny("invalid_snapshot_option") end
                bytes=bytes+#k
                if type(v)=="table" then
                    for i=1,list(v) do bytes=bytes+#v[i] end
                elseif text(v) then bytes=bytes+#v
                else deny("invalid_snapshot_option") end
            end
        end
    end
    if bytes>131072 then deny("snapshot_too_large") end
    return s
end
-- Bounded parser for native 'uci export'. It implements quoting/escaping,
-- not shell execution or interpolation. All duplicate records fail closed.
local function tokens(line)
    local out,buf,quote,active={}, {},nil,false
    local i=1
    local function flush()
        if active then out[#out+1]=table.concat(buf);buf={};active=false end
    end
    while i<=#line do
        local c=line:sub(i,i)
        if quote then
            if c==quote then quote=nil
            elseif c=="\\" and quote=='"' then
                i=i+1;if i>#line then deny("export_syntax_invalid") end
                local nextchar=line:sub(i,i)
                if nextchar~=quote and nextchar~="\\" then buf[#buf+1]="\\" end
                buf[#buf+1]=nextchar
            else buf[#buf+1]=c end
        elseif c=="'" or c=='"' then quote=c;active=true
        elseif c=="#" then break
        elseif c==" " or c=="\t" or c=="\r" then flush()
        elseif c=="\\" then
            active=true;i=i+1;if i>#line then deny("export_syntax_invalid") end
            buf[#buf+1]=line:sub(i,i)
        else active=true;buf[#buf+1]=c end
        i=i+1
    end
    if quote then deny("export_syntax_invalid") end
    flush()
    if #out>3 then deny("unsupported_export_record") end
    for _,v in ipairs(out) do if not text(v) then deny("export_value_invalid") end end
    return out
end
local function parse(raw,package)
    if type(raw)~="string" or #raw>65536 or not ident(package) then deny("export_size_invalid") end
    local sections,counts,current,header={}, {},nil,false
    for line in (raw.."\n"):gmatch("(.-)\n") do
        local p=tokens(line)
        if #p==0 then
        elseif p[1]=="package" and #p==2 and not header and next(sections)==nil then
            if p[2]~=package then deny("export_package_mismatch") end;header=true
        elseif p[1]=="config" and (#p==2 or #p==3) and header then
            if not ident(p[2]) then deny("export_section_type_invalid") end
            local i=counts[p[2]] or 0;counts[p[2]]=i+1
            local name=p[3] or ("@"..p[2].."["..i.."]")
            if p[3] and not ident(p[3]) then deny("export_section_name_invalid") end
            if sections[name] then deny("duplicate_export_section") end
            current={type=p[2],options={}};sections[name]=current
        elseif (p[1]=="option" or p[1]=="list") and #p==3 and current then
            if not ident(p[2]) then deny("export_option_invalid") end
            local opts=current.options
            if p[1]=="option" then
                if opts[p[2]]~=nil then deny("duplicate_export_option") end
                opts[p[2]]=p[3]
            else
                if opts[p[2]]~=nil and type(opts[p[2]])~="table" then deny("mixed_scalar_and_list") end
                opts[p[2]]=opts[p[2]] or {};local v=opts[p[2]];v[#v+1]=p[3]
                if #v>64 then deny("export_list_too_long") end
            end
        else deny("unsupported_export_record") end
    end
    if not header then deny("export_header_missing") end
    bounded_snapshot({network=sections,firewall={}})
    return sections
end
local function safe(fn,...)
    local ok,a=pcall(fn,...)
    if ok then return a end
    if type(a)=="table" and rawget(a,"tag")==ERROR_TAG then return nil,rawget(a,"code") end
    return nil,"candidate_internal_error"
end
function M.parse_export(raw,package) return safe(parse,raw,package) end
local function ipv4(s)
    if type(s)~="string" then return nil end
    local a,b,c,d=s:match("^(%d+)%.(%d+)%.(%d+)%.(%d+)$")
    if not a then return nil end
    local v={a,b,c,d};local n=0
    for _,p in ipairs(v) do
        if #p>3 or (#p>1 and p:sub(1,1)=="0") or tonumber(p)>255 then return nil end
        n=n*256+tonumber(p)
    end
    return n,tonumber(a)
end
local function address(opts)
    local n,first=ipv4(opts.ipaddr)
    if not n or n==0 or first==127 or (first>=224 and first<=239) then
        deny("management_ipv4_profile_unqualified")
    end
    local mask=ipv4(opts.netmask);local valid=false
    if mask then
        for bits=0,32 do if mask==4294967296-2^(32-bits) then valid=true;break end end
    elseif type(opts.netmask)=="string" and opts.netmask:match("^%d+$") and
           tonumber(opts.netmask)<=32 then valid=true end
    if not valid or (opts.gateway and opts.gateway~="" and not ipv4(opts.gateway)) then
        deny("management_ipv4_profile_unqualified")
    end
end
local function members(zone)
    local v=zone.options.network
    if v==nil then return {} end
    local r={}
    if type(v)=="table" then for i=1,list(v) do r[i]=v[i] end
    elseif type(v)=="string" then
        for k in v:gmatch("%S+") do r[#r+1]=k end
        if table.concat(r," ")~=v then deny("noncanonical_zone_membership") end
    else deny("ambiguous_zone_membership") end
    local seen={}
    for _,k in ipairs(r) do
        if not ident(k) or seen[k] then deny("ambiguous_zone_membership") end;seen[k]=true
    end
    return r
end
local function has(r,s) for _,v in ipairs(r) do if v==s then return true end end;return false end
local function replace_members(zone,r)
    zone.options.network=type(zone.options.network)=="table" and r or table.concat(r," ")
end
local function allowed(opts,allow,extra)
    for k in pairs(opts) do if not allow[k] and k~=extra then return false end end
    return true
end
local function prepare(snapshot,vlan,parent,zone_name)
    bounded_snapshot(snapshot)
    if type(vlan)~="number" or vlan~=math.floor(vlan) or vlan<0 or vlan>4094 then
        deny("vlan_not_explicitly_supported")
    end
    if not ident(parent) or #parent>32 then deny("parent_unqualified") end
    if not ident(zone_name) or zone_name=="wan" then deny("trusted_zone_unqualified") end
    local desired=copy(snapshot);local net,fw=desired.network,desired.firewall
    local lct=net.lct
    if not lct or lct.type~="interface" or lct.options.ifname~=parent or
       lct.options.proto~="static" or not allowed(lct.options,LCT) then deny("lct_profile_unqualified") end
    local opts=lct.options
    for name in pairs(net) do
        if name:match("^@interface%[") then deny("anonymous_network_interface_unqualified") end
    end
    local owned=net.mgmt~=nil or net.lct_vlan~=nil
    local source=opts
    if owned then
        local mgmt,device=net.mgmt,net.lct_vlan
        local mo=mgmt and mgmt.options;local d=device and device.options
        if not mgmt or not device or mgmt.type~="interface" or device.type~="device" or
           mo.aott_owner~=OWNER or d.aott_owner~=OWNER or mo.ifname~="mgmt" or mo.proto~="static" or
           d.ifname~=parent or d.name~="mgmt" or d.type~="8021q" or
           not allowed(mo,LCT,"aott_owner") or not allowed(d,DEVICE) or
           type(d.vid)~="string" or not d.vid:match("^%d+$") or
           tonumber(d.vid)<1 or tonumber(d.vid)>4094 then deny("legacy_or_foreign_interface_ownership") end
        for k in pairs(DEVICE) do if d[k]==nil then deny("legacy_or_foreign_interface_ownership") end end
        for _,k in ipairs(ADDRESS) do if opts[k]~=nil then deny("legacy_or_foreign_interface_ownership") end end
        if mo.macaddr~=opts.macaddr then deny("management_mac_profile_mismatch") end
        source=mo
    end
    address(source)
    for name,section in pairs(net) do
        if name~="lct" and name~="mgmt" and name~="lct_vlan" then
            for _,key in ipairs({"ifname","device","interface","name"}) do
                local value=section.options[key] or {};local v={}
                if type(value)=="table" then v=value else for p in value:gmatch("%S+") do v[#v+1]=p end end
                if has(v,"mgmt") or has(v,"lct_vlan") then deny("foreign_management_reference") end
            end
        end
    end
    local zid,zone=nil,nil
    for name,section in pairs(fw) do
        if section.type=="zone" and section.options.name==zone_name then
            if zone then deny("trusted_zone_not_unique") end;zid=name;zone=section
        end
    end
    if not zone then deny("trusted_zone_not_unique") end
    local names=members(zone)
    if not has(names,"lct") or (owned and not has(names,"mgmt")) or
       (not owned and has(names,"mgmt")) then deny("management_zone_binding_unqualified") end
    for name,s in pairs(fw) do
        if s.type=="zone" and name~=zid then
            local v=members(s)
            if has(v,"lct") or has(v,"mgmt") then deny("management_in_multiple_zones") end
        end
    end
    if vlan>0 then
        local mo={ifname="mgmt",proto="static",auto=source.auto or "1",aott_owner=OWNER}
        for _,k in ipairs(ADDRESS) do mo[k]=copy(source[k]);opts[k]=nil end
        mo.macaddr=opts.macaddr
        net.mgmt={type="interface",options=mo}
        net.lct_vlan={type="device",options={ifname=parent,name="mgmt",type="8021q",vid=tostring(vlan),aott_owner=OWNER}}
        if not has(names,"mgmt") then names[#names+1]="mgmt";replace_members(zone,names) end
    elseif owned then
        for _,k in ipairs(ADDRESS) do opts[k]=copy(source[k]) end
        net.mgmt=nil;net.lct_vlan=nil
        local new={};for _,v in ipairs(names) do if v~="mgmt" then new[#new+1]=v end end
        replace_members(zone,new)
    end
    bounded_snapshot(desired)
    local ops={}
    local function add(verb,path) ops[#ops+1]={verb,path};if #ops>512 then deny("too_many_operations") end end
    for _,pkg in ipairs({"network","firewall"}) do
        local before,after=snapshot[pkg],desired[pkg];local all={}
        for k in pairs(before) do all[k]=true end;for k in pairs(after) do all[k]=true end
        for _,name in ipairs(keys(all)) do
            local left,right=before[name],after[name];local key=pkg.."."..name
            if not right then add("delete",key)
            else
                if not left then add("set",key.."="..right.type) end
                local old=left and left.options or {};local options={}
                for k in pairs(old) do options[k]=true end;for k in pairs(right.options) do options[k]=true end
                for _,option in ipairs(keys(options)) do
                    local prev,val=old[option],right.options[option];local path=key.."."..option
                    if not equal(prev,val) then
                        if val==nil or type(prev)=="table" or type(val)=="table" then
                            if prev~=nil then add("delete",path) end
                        end
                        if type(val)=="table" then for _,v in ipairs(val) do add("add_list",path.."="..v) end
                        elseif val~=nil then add("set",path.."="..val) end
                    end
                end
            end
        end
    end
    local handle={}
    plans[handle]={before=copy(snapshot),after=desired,operations=ops}
    return handle
end
function M.prepare(snapshot,vlan,parent,zone) return safe(prepare,snapshot,vlan,parent,zone) end
-- Test-only projection contains synthetic configuration. Never expose it in a
-- GUI or log. Copies cannot alter the private plan used by verify_staged.
function M.fixture_projection(handle,mode)
    if mode~="offline_synthetic" or not plans[handle] then return nil,"invalid_plan_handle" end
    return copy({after=plans[handle].after,operations=plans[handle].operations})
end
local function execute(handle,adapter,mode)
    local plan=plans[handle]
    if mode~="offline_synthetic" or not plan then deny("invalid_plan_handle") end
    if type(adapter)~="table" or adapter.disposable_fixture~=true or
       type(adapter.snapshot)~="function" or type(adapter.persisted_snapshot)~="function" or
       type(adapter.command)~="function" then deny("private_candidate_adapter_required") end
    local current=bounded_snapshot(adapter.snapshot())
    if not equal(current,plan.before) then deny("stale_candidate_revision") end
    for _,op in ipairs(plan.operations) do
        if adapter.command(copy(op))~=true then deny("candidate_mutation_failed") end
    end
    -- A semantic no-op must not rewrite either package merely for validation.
    if #plan.operations>0 then
        for _,pkg in ipairs({"network","firewall"}) do
            if adapter.command({"commit",pkg})~=true then deny("candidate_commit_failed") end
        end
    end
    local persisted=bounded_snapshot(adapter.persisted_snapshot())
    if not equal(persisted,plan.after) then deny("candidate_readback_mismatch") end
    return {status="SOURCE_LUA_UCI_CANDIDATE_VALIDATED",operations_checked=#plan.operations,
        source_only_not_deployed=true,live_promote_available=false,
        hardware_network_and_recovery_unverified=true,contains_configuration_values=false}
end
function M.verify_staged(handle,adapter,mode) return safe(execute,handle,adapter,mode) end
return M
