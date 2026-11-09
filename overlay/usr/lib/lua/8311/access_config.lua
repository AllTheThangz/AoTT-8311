-- AoTT-8311 V3 canonical access/server product configuration.
-- Fixed UCI mappings only. No arbitrary package/section/option input.
local uci_lib=require "luci.model.uci"
local web=require "8311.webutil"
local remote_firewall=require "8311.remote_firewall"
local M={}

local FIELDS={
    {id="ssh_enabled",type="bool",default="1"},
    {id="ssh_port",type="uint",min=1,max=65535,default="22"},
    {id="ssh_password_auth",type="bool",default="1"},
    {id="ssh_root_password_auth",type="bool",default="1"},
    {id="ssh_root_login",type="bool",default="1"},
    {id="ssh_gateway_ports",type="bool",default="0"},
    {id="ssh_keepalive",type="uint",min=0,max=86400,default="300"},
    {id="ssh_idle_timeout",type="uint",min=0,max=86400,default="0"},
    {id="ssh_max_auth_tries",type="uint",min=1,max=20,default="3"},
    {id="ssh_mdns",type="bool",default="1"},
    {id="luci_sessiontime",type="uint",min=300,max=86400,default="3600"},
    {id="web_http_port",type="optional_port",default="80"},
    {id="web_https_port",type="uint",min=1,max=65535,default="443"},
    {id="web_script_timeout",type="uint",min=1,max=3600,default="60"},
    {id="web_network_timeout",type="uint",min=1,max=3600,default="30"},
    {id="web_http_keepalive",type="uint",min=0,max=3600,default="20"},
    {id="web_tcp_keepalive",type="uint",min=0,max=3600,default="1"},
    {id="web_max_requests",type="uint",min=1,max=100,default="3"},
    {id="web_max_connections",type="uint",min=1,max=1024,default="100"},
    {id="web_rfc1918_filter",type="bool",default="1"},
    {id="remote_gui_enabled",type="bool",default="0"},
    {id="remote_gui_ipv4_sources",type="cidr4_list",default=""},
}
local FIELD={}
for _,row in ipairs(FIELDS) do FIELD[row.id]=row end

local DROP={
    ssh_enabled={"enable","1"},
    ssh_port={"Port","22"},
    ssh_password_auth={"PasswordAuth","1"},
    ssh_root_password_auth={"RootPasswordAuth","1"},
    ssh_root_login={"RootLogin","1"},
    ssh_gateway_ports={"GatewayPorts","0"},
    ssh_keepalive={"SSHKeepAlive","300"},
    ssh_idle_timeout={"IdleTimeout","0"},
    ssh_max_auth_tries={"MaxAuthTries","3"},
    ssh_mdns={"mdns","1"},
}
local WEB={
    web_script_timeout={"script_timeout","60"},
    web_network_timeout={"network_timeout","30"},
    web_http_keepalive={"http_keepalive","20"},
    web_tcp_keepalive={"tcp_keepalive","1"},
    web_max_requests={"max_requests","3"},
    web_max_connections={"max_connections","100"},
    web_rfc1918_filter={"rfc1918_filter","1"},
}

local function ipv4(value)
    if type(value)~="string" or #value>15 then return nil end
    local a,b,c,d=value:match("^(%d+)%.(%d+)%.(%d+)%.(%d+)$")
    if not a then return nil end
    for _,v in ipairs({a,b,c,d}) do
        if #v>3 or (#v>1 and v:sub(1,1)=="0") or tonumber(v)>255 then return nil end
    end
    return value
end

local function unique_section(cursor,package,kind)
    local names={}
    cursor:foreach(package,kind,function(row)
        if type(row)=="table" and type(row[".name"])=="string" then
            names[#names+1]=row[".name"]
        end
    end)
    if #names~=1 then return nil,package.."_section_not_unique" end
    return names[1]
end

local function boolean(value,default)
    if value==nil or value=="" then value=default end
    if value=="1" or value=="on" or value=="true" then return "1" end
    if value=="0" or value=="off" or value=="false" then return "0" end
end

local function uint(value,default,low,high)
    if value==nil or value=="" then value=default end
    if type(value)~="string" or not value:match("^%d+$") or
       (#value>1 and value:sub(1,1)=="0") or #value>10 then return nil end
    local n=tonumber(value)
    if not n or n<low or n>high then return nil end
    return tostring(n)
end

local function listener_port(values)
    if values==nil then return "",{}, "disabled" end
    if type(values)=="string" then values={values} end
    if type(values)~="table" or #values>8 then return nil,nil,"listener_list_invalid" end
    if #values==0 then return "",{},"disabled" end
    local port=nil
    local clean={}
    for i,value in ipairs(values) do
        if type(value)~="string" or #value>96 or value:find("[%z\1-\31\127]") then
            return nil,nil,"listener_invalid"
        end
        local p=value:match("^%d+%.%d+%.%d+%.%d+:(%d+)$") or
                value:match("^%[[0-9A-Fa-f:]+%]:(%d+)$")
        if not p then return nil,nil,"listener_format_unsupported" end
        p=uint(p,nil,1,65535)
        if not p or (port and p~=port) then return nil,nil,"listener_ports_not_uniform" end
        port=p
        clean[i]=value
    end
    return port,clean,"configured"
end

local function management_ip(cursor)
    local value=cursor:get("network","mgmt","ipaddr")
    if not ipv4(value) then value=cursor:get("network","lct","ipaddr") end
    return ipv4(value)
end

local function canonical(snapshot)
    local rows={}
    for _,field in ipairs(FIELDS) do
        rows[#rows+1]=field.id.."="..tostring(snapshot.values[field.id] or "")
    end
    rows[#rows+1]="http_scope="..snapshot.http_scope
    rows[#rows+1]="https_scope="..snapshot.https_scope
    for _,value in ipairs(snapshot.http_listeners or {}) do rows[#rows+1]="http="..value end
    for _,value in ipairs(snapshot.https_listeners or {}) do rows[#rows+1]="https="..value end
    return table.concat(rows,"\n")
end

function M.snapshot(adapter)
    local cursor=adapter or uci_lib.cursor()
    local drop,why=unique_section(cursor,"dropbear","dropbear")
    if not drop then return nil,why end
    local main=cursor:get_all("uhttpd","main")
    local sauth=cursor:get_all("luci","sauth")
    if type(main)~="table" or main[".type"]~="uhttpd" then
        return nil,"uhttpd_main_unavailable"
    end
    if type(sauth)~="table" or sauth[".type"]~="internal" then
        return nil,"luci_sauth_unavailable"
    end
    local ip=management_ip(cursor)
    if not ip then return nil,"management_ipv4_unavailable" end

    local values={}
    for id,map in pairs(DROP) do
        local raw=cursor:get("dropbear",drop,map[1])
        if FIELD[id].type=="bool" then
            values[id]=boolean(raw,map[2])
        else
            values[id]=uint(raw,map[2],FIELD[id].min,FIELD[id].max)
        end
        if values[id]==nil then return nil,"invalid_saved_"..id end
    end
    values.luci_sessiontime=uint(cursor:get("luci","sauth","sessiontime"),
        "3600",300,86400)
    if not values.luci_sessiontime then return nil,"invalid_saved_luci_sessiontime" end
    for id,map in pairs(WEB) do
        local raw=cursor:get("uhttpd","main",map[1])
        if FIELD[id].type=="bool" then values[id]=boolean(raw,map[2])
        else values[id]=uint(raw,map[2],FIELD[id].min,FIELD[id].max) end
        if values[id]==nil then return nil,"invalid_saved_"..id end
    end
    local http,http_list,http_state=listener_port(cursor:get_list("uhttpd","main","listen_http"))
    local https,https_list,https_state=listener_port(cursor:get_list("uhttpd","main","listen_https"))
    if http==nil then return nil,http_state end
    if https==nil or https=="" then return nil,https_state=="disabled" and
        "https_listener_required" or https_state end
    values.web_http_port=http
    values.web_https_port=https
    local remote,remote_why=remote_firewall.snapshot(cursor,ip,https)
    if not remote then return nil,remote_why end
    values.remote_gui_enabled=remote.enabled
    values.remote_gui_ipv4_sources=remote.sources
    local function scope(list,port)
        if #list==0 then return "disabled" end
        if #list==1 and list[1]==ip..":"..port then return "management_ipv4_only" end
        return "legacy_or_multi_listener"
    end
    local snapshot={
        schema=1,values=values,management_ip=ip,
        dropbear_section=drop,
        http_listeners=http_list,https_listeners=https_list,
        http_scope=scope(http_list,http),https_scope=scope(https_list,https),
    }
    local revision,rev_why=web.digest_text(canonical(snapshot))
    if not revision then return nil,rev_why end
    snapshot.revision=revision
    return snapshot
end

function M.public_snapshot(snapshot)
    if type(snapshot)~="table" or type(snapshot.values)~="table" then return nil end
    local values={}
    for _,f in ipairs(FIELDS) do values[f.id]=snapshot.values[f.id] end
    return {
        schema=1,revision=snapshot.revision,values=values,
        http_scope=snapshot.http_scope,https_scope=snapshot.https_scope,
        fields=FIELDS,
        contains_management_address=false,contains_credentials=false,
    }
end

function M.validate(id,value)
    local f=FIELD[id]
    if not f or type(value)~="string" or #value>64 or value:find("[%z\1-\31\127]") then
        return nil,"Invalid value"
    end
    if f.type=="bool" then
        return (value=="0" or value=="1") and value or nil,
               (value=="0" or value=="1") and nil or "Choose enabled or disabled"
    elseif f.type=="optional_port" then
        if value=="" then return "" end
        local v=uint(value,nil,1,65535)
        return v,v and nil or "Enter a TCP port from 1 to 65535 or leave blank to disable HTTP"
    elseif f.type=="uint" then
        local v=uint(value,nil,f.min,f.max)
        return v,v and nil or ("Enter a whole number from "..f.min.." to "..f.max)
    elseif f.type=="cidr4_list" then
        local v,why=remote_firewall.normalize_sources(value)
        return v,v and nil or (why or "Enter one or more IPv4 CIDRs")
    end
    return nil,"Unsupported field"
end

local LOCKOUT={
    ssh_enabled=true,ssh_port=true,ssh_password_auth=true,
    ssh_root_password_auth=true,ssh_root_login=true,
    web_http_port=true,web_https_port=true,
    remote_gui_enabled=true,remote_gui_ipv4_sources=true,
}

function M.prepare(snapshot,form)
    if type(snapshot)~="table" or type(snapshot.values)~="table" or
       type(form)~="table" or getmetatable(form)~=nil then
        return nil,{request="Invalid access form"},400
    end
    if form.revision~=snapshot.revision then
        return nil,{revision="Access configuration changed; reload and review again"},409
    end
    local known={revision=true,token=true,mode=true}
    local desired,errors,diff={}, {}, {}
    for _,field in ipairs(FIELDS) do
        known[field.id]=true
        local value,why=M.validate(field.id,form[field.id])
        if value==nil then errors[field.id]=why else
            desired[field.id]=value
            if value~=snapshot.values[field.id] then
                diff[#diff+1]={
                    id=field.id,before=snapshot.values[field.id],after=value,
                    confirmation_required=LOCKOUT[field.id]==true,
                }
            end
        end
    end
    for key,value in pairs(form) do
        if not known[key] or type(value)~="string" then
            errors.request="Unknown or duplicate access field"
        end
    end
    local hp=desired.web_http_port
    local sp=desired.ssh_port
    local tp=desired.web_https_port
    if hp~="" and hp==tp then errors.web_http_port="HTTP and HTTPS ports must differ" end
    if desired.ssh_enabled=="1" then
        if sp==tp then errors.ssh_port="SSH and HTTPS ports must differ" end
        if hp~="" and sp==hp then errors.ssh_port="SSH and HTTP ports must differ" end
    end
    if desired.remote_gui_enabled=="1" and desired.remote_gui_ipv4_sources=="" then
        errors.remote_gui_ipv4_sources="Remote HTTPS requires at least one explicit IPv4 source CIDR"
    end
    if next(errors) then return nil,errors,422 end
    local disruptive=false
    for _,row in ipairs(diff) do if row.confirmation_required then disruptive=true end end
    return {
        schema=1,revision=snapshot.revision,desired=desired,diff=diff,
        changes_required=#diff>0,confirmation_required=disruptive or #diff>0,
        listener_migration_required=
            (snapshot.http_scope=="legacy_or_multi_listener" or
             snapshot.https_scope=="legacy_or_multi_listener") and #diff>0,
    }
end

function M.request_ok(args)
    if type(args)~="table" or getmetatable(args)~=nil or
       type(args.revision)~="string" or #args.revision~=64 or
       args.revision:find("[^0-9a-f]") then return nil end
    local out={revision=args.revision}
    for _,field in ipairs(FIELDS) do
        local value=M.validate(field.id,args[field.id])
        if value==nil then return nil end
        out[field.id]=value
    end
    for key in pairs(args) do
        if key~="revision" and not FIELD[key] then return nil end
    end
    return out
end

function M.desired_from_request(args)
    local clean=M.request_ok(args)
    if not clean then return nil end
    local desired={}
    for _,field in ipairs(FIELDS) do desired[field.id]=clean[field.id] end
    return desired
end

M.fields=FIELDS
M.field_map=FIELD
M.dropbear_map=DROP
M.web_map=WEB
M.canonical=canonical
return M
