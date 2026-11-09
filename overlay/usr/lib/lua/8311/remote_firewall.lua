-- AoTT-8311 V3 optional residential remote HTTPS firewall policy.
-- Generates only fixed-name firewall INPUT rules for the management HTTPS
-- endpoint. It never changes forwarding, NAT, PON, OMCI, or arbitrary zones.
local web=require "8311.webutil"
local M={}

local PREFIX="AoTT-Remote-HTTPS-"
local SECTION_PREFIX="aott_remote_https_"
local MAX_RULES=8

local function ipv4(value)
    if type(value)~="string" or #value>15 then return nil end
    local a,b,c,d=value:match("^(%d+)%.(%d+)%.(%d+)%.(%d+)$")
    if not a then return nil end
    local parts={a,b,c,d}
    local n=0
    for _,part in ipairs(parts) do
        if #part>3 or (#part>1 and part:sub(1,1)=="0") then return nil end
        local x=tonumber(part);if not x or x>255 then return nil end
        n=n*256+x
    end
    local first=tonumber(a)
    if first==0 or first==127 or first>=224 or
       (first==169 and tonumber(b)==254) then return nil end
    return n,table.concat({tonumber(a),tonumber(b),tonumber(c),tonumber(d)},".")
end

local function number_ip(n)
    local a=math.floor(n/16777216)%256
    local b=math.floor(n/65536)%256
    local c=math.floor(n/256)%256
    local d=n%256
    return table.concat({a,b,c,d},".")
end

local function parse_cidrs(text)
    if type(text)~="string" or #text>1024 or text:find("[%z\1-\31\127]") then
        return nil,"remote_source_list_invalid"
    end
    local out,seen={},{}
    for token in text:gmatch("[^,%s]+") do
        if #out>=MAX_RULES then return nil,"too_many_remote_sources" end
        local address,prefix=token:match("^([^/]+)/(%d+)$")
        if not address or not prefix or #prefix>2 then return nil,"explicit_ipv4_cidr_required" end
        prefix=tonumber(prefix)
        if not prefix or prefix<24 or prefix>32 then return nil,"remote_source_scope_too_broad" end
        local value=ipv4(address);if not value then return nil,"remote_source_cidr_invalid" end
        local block=2^(32-prefix)
        local network=math.floor(value/block)*block
        if network~=value then return nil,"remote_source_cidr_not_network" end
        local canonical=number_ip(network).."/"..tostring(prefix)
        if seen[canonical] then return nil,"duplicate_remote_source" end
        -- Reject overlapping networks to keep the generated policy obvious.
        for _,row in ipairs(out) do
            local existing=row.network
            local size=row.block
            if (network>=existing and network<existing+size) or
               (existing>=network and existing<network+block) then
                return nil,"overlapping_remote_sources"
            end
        end
        seen[canonical]=true
        out[#out+1]={text=canonical,network=network,block=block}
    end
    table.sort(out,function(a,b) return a.network<b.network or
        (a.network==b.network and a.block<b.block) end)
    local texts={}
    for _,row in ipairs(out) do texts[#texts+1]=row.text end
    return texts
end

local function bool(value)
    if value=="1" or value=="on" or value=="true" then return "1" end
    if value=="0" or value=="off" or value=="false" or value==nil or value=="" then return "0" end
end

local function rules(cursor)
    local out={}
    cursor:foreach("firewall","rule",function(row)
        if type(row)=="table" and type(row[".name"])=="string" and
           type(row.name)=="string" and row.name:match("^AoTT%-Remote%-HTTPS%-%d+$") then
            out[#out+1]=row
        end
    end)
    table.sort(out,function(a,b)return a.name<b.name end)
    if #out>MAX_RULES then return nil,"remote_rule_count_exceeded" end
    return out
end

function M.normalize_sources(text)
    local rows,why=parse_cidrs(text or "")
    if not rows then return nil,why end
    return table.concat(rows," "),rows
end

function M.snapshot(cursor,management_ip,https_port)
    local ip=select(2,ipv4(management_ip))
    if not ip or type(https_port)~="string" or not https_port:match("^%d+$") or
       tonumber(https_port)<1 or tonumber(https_port)>65535 then
        return nil,"remote_firewall_target_invalid"
    end
    local found,why=rules(cursor);if not found then return nil,why end
    if #found==0 then
        return {enabled="0",sources="",rules=0,management_ip=ip,https_port=https_port}
    end
    local sources={}
    local enabled=nil
    for index,row in ipairs(found) do
        local row_enabled=bool(row.enabled)
        if row.name~=PREFIX..tostring(index) or
           row.src~="wan" or row.dest_ip~=ip or row.dest_port~=https_port or
           row.proto~="tcp" or row.family~="ipv4" or row.target~="ACCEPT" or
           row_enabled==nil then
            return nil,"remote_firewall_existing_rule_unqualified"
        end
        if enabled==nil then enabled=row_enabled
        elseif enabled~=row_enabled then return nil,"remote_firewall_mixed_enable_state" end
        local normalized=parse_cidrs(row.src_ip or "")
        if not normalized or #normalized~=1 then return nil,"remote_firewall_existing_source_invalid" end
        sources[#sources+1]=normalized[1]
    end
    local joined,rows=M.normalize_sources(table.concat(sources," "))
    if not joined then return nil,rows end
    return {enabled=enabled or "0",sources=joined,rules=#sources,management_ip=ip,https_port=https_port}
end

local function remove_existing(cursor)
    local found,why=rules(cursor);if not found then return nil,why end
    for _,row in ipairs(found) do
        if cursor:delete("firewall",row[".name"])~=true then
            return nil,"remote_firewall_rule_delete_failed"
        end
    end
    return true
end

function M.apply(cursor,management_ip,https_port,enabled,sources)
    enabled=bool(enabled)
    if not enabled then return nil,"remote_firewall_enable_invalid" end
    local normalized,rows=M.normalize_sources(sources or "")
    if not normalized then return nil,rows end
    if enabled=="1" and #rows<1 then return nil,"remote_firewall_sources_required" end
    local ip=select(2,ipv4(management_ip));if not ip then return nil,"remote_firewall_target_invalid" end
    local current_port=tostring(tonumber(https_port) or 0)
    if current_port=="0" then return nil,"remote_firewall_port_invalid" end
    local before,before_why=M.snapshot(cursor,ip,current_port)
    if not before then return nil,before_why end
    if before.enabled==enabled and before.sources==normalized then
        return {status="REMOTE_FIREWALL_UCI_UNCHANGED",enabled=enabled,
                rule_count=before.rules,contains_management_address=false}
    end

    local ok,why=remove_existing(cursor);if not ok then return nil,why end
    if #rows>0 then
        for index,source in ipairs(rows) do
            local section=SECTION_PREFIX..tostring(index)
            local existing=cursor:get_all("firewall",section)
            if existing~=nil then return nil,"remote_firewall_section_collision" end
            local name=cursor:section("firewall","rule",section,{
                name=PREFIX..tostring(index),enabled=enabled,src="wan",
                src_ip=source,dest_ip=ip,dest_port=current_port,
                proto="tcp",family="ipv4",target="ACCEPT",
            })
            if name~=section then return nil,"remote_firewall_rule_stage_failed" end
        end
    end
    if cursor:commit("firewall")~=true then return nil,"remote_firewall_commit_failed" end
    local state,state_why=M.snapshot(cursor,ip,current_port)
    if not state then return nil,state_why end
    if state.enabled~=enabled or state.sources~=normalized then
        return nil,"remote_firewall_readback_mismatch"
    end
    return {status="REMOTE_FIREWALL_UCI_APPLIED",enabled=enabled,
            rule_count=state.rules,contains_management_address=false}
end

function M.verify(cursor,management_ip,https_port,enabled,sources)
    local desired,rows=M.normalize_sources(sources or "")
    if not desired then return nil,rows end
    local state,why=M.snapshot(cursor,management_ip,https_port)
    if not state then return nil,why end
    enabled=bool(enabled)
    if state.enabled~=enabled or state.sources~=desired then
        return nil,"remote_firewall_uci_mismatch"
    end
    local code,_,overflow=web.capture({"/sbin/fw3","-4","print"},262144)
    if code~=0 or overflow then return nil,"remote_firewall_fw3_render_failed" end
    return {
        status="REMOTE_FIREWALL_VERIFIED",
        enabled=enabled,rule_count=state.rules,
        fw3_render_verified=true,kernel_packet_path_unverified=true,
        bridge_forwarding_not_modified_by_policy=true,
        contains_management_address=false,
    }
end

M.MAX_RULES=MAX_RULES
return M
