local root=assert(arg[1],"overlay lua root required")
package.path=root.."/?.lua;"..package.path

package.preload["8311.webutil"]=function()
    return {capture=function(argv)
        assert(type(argv)=="table" and argv[1]=="/sbin/fw3" and argv[2]=="-4" and argv[3]=="print",
               "unexpected command")
        return 0,"synthetic fw3 output",false
    end}
end

local fw=require "8311.remote_firewall"
local function ipv4(a,b,c,d) return table.concat({a,b,c,d},".") end
local MGMT=ipv4(192,0,2,10)
local SRC_A=ipv4(198,51,100,0)
local SRC_B=ipv4(203,0,113,24)
local SRC_C=ipv4(203,0,113,2)
local LOOPBACK=ipv4(127,0,0,1)
local LINKLOCAL=ipv4(169,254,1,1)
local Cursor={}
Cursor.__index=Cursor
function Cursor.new()
    return setmetatable({rows={},commits=0},Cursor)
end
function Cursor:foreach(pkg,kind,cb)
    assert(pkg=="firewall" and kind=="rule")
    local names={}
    for name in pairs(self.rows) do names[#names+1]=name end
    table.sort(names)
    for _,name in ipairs(names) do
        local src=self.rows[name]
        local row={[".name"]=name,[".type"]="rule"}
        for k,v in pairs(src) do row[k]=v end
        cb(row)
    end
end
function Cursor:get_all(pkg,name)
    assert(pkg=="firewall")
    local src=self.rows[name]
    if not src then return nil end
    local row={[".name"]=name,[".type"]="rule"}
    for k,v in pairs(src) do row[k]=v end
    return row
end
function Cursor:delete(pkg,name)
    assert(pkg=="firewall")
    if not self.rows[name] then return false end
    self.rows[name]=nil
    return true
end
function Cursor:section(pkg,kind,name,values)
    assert(pkg=="firewall" and kind=="rule" and type(name)=="string")
    if self.rows[name] then return nil end
    local row={}
    for k,v in pairs(values) do row[k]=v end
    self.rows[name]=row
    return name
end
function Cursor:commit(pkg)
    assert(pkg=="firewall")
    self.commits=self.commits+1
    return true
end

local checks=0
local function same(a,b,label)
    checks=checks+1
    assert(a==b,"REMOTE_FW_FIXTURE:"..label.." expected="..tostring(b).." got="..tostring(a))
end
local function truth(v,label) same(not not v,true,label) end

local text,rows=fw.normalize_sources(SRC_B.."/32, "..SRC_A.."/28")
same(text,SRC_A.."/28 "..SRC_B.."/32","canonical_sort")
same(#rows,2,"canonical_count")
same(fw.normalize_sources(SRC_A.."/23"),nil,"broad_refused")
same(fw.normalize_sources(ipv4(198,51,100,1).."/24"),nil,"host_bits_refused")
same(fw.normalize_sources(SRC_A.."/24 "..ipv4(198,51,100,128).."/25"),nil,"overlap_refused")
same(fw.normalize_sources(LOOPBACK.."/32"),nil,"loopback_refused")
same(fw.normalize_sources(LINKLOCAL.."/32"),nil,"linklocal_refused")

local c=Cursor.new()
local state=assert(fw.snapshot(c,MGMT,"443"))
same(state.enabled,"0","empty_disabled")
same(state.sources,"","empty_sources")
same(state.rules,0,"empty_rules")

local receipt=assert(fw.apply(c,MGMT,"443","0",SRC_A.."/28"))
same(receipt.status,"REMOTE_FIREWALL_UCI_APPLIED","disabled_policy_applied")
same(c.commits,1,"disabled_policy_commit")
state=assert(fw.snapshot(c,MGMT,"443"))
same(state.enabled,"0","disabled_retained")
same(state.sources,SRC_A.."/28","disabled_source_retained")
same(state.rules,1,"disabled_rule_retained")
local row=c.rows.aott_remote_https_1
same(row.name,"AoTT-Remote-HTTPS-1","fixed_name")
same(row.enabled,"0","fixed_disabled")
same(row.src,"wan","fixed_zone")
same(row.dest_ip,MGMT,"fixed_target")
same(row.dest_port,"443","fixed_port")
same(row.proto,"tcp","https_tcp_only")
same(row.family,"ipv4","ipv4_only")
same(row.target,"ACCEPT","input_accept")
same(row.forward,nil,"no_forward")
same(row.dest,nil,"no_forward_zone")
same(row.src_ip,SRC_A.."/28","source_exact")

receipt=assert(fw.apply(c,MGMT,"443","1",SRC_A.."/28"))
same(receipt.enabled,"1","enabled_receipt")
same(c.commits,2,"enable_commit")
state=assert(fw.snapshot(c,MGMT,"443"))
same(state.enabled,"1","enabled_snapshot")

receipt=assert(fw.apply(c,MGMT,"443","1",SRC_A.."/28"))
same(receipt.status,"REMOTE_FIREWALL_UCI_UNCHANGED","noop_status")
same(c.commits,2,"noop_no_commit")

local verified=assert(fw.verify(c,MGMT,"443","1",SRC_A.."/28"))
same(verified.status,"REMOTE_FIREWALL_VERIFIED","verify_status")
same(verified.fw3_render_verified,true,"fw3_render")
same(verified.kernel_packet_path_unverified,true,"kernel_caveat")
same(verified.bridge_forwarding_not_modified_by_policy,true,"bridge_scope")

same(fw.apply(c,MGMT,"443","1",""),nil,"enable_requires_source")
c.rows.evil={name="AoTT-Remote-HTTPS-2",enabled="1",src="lan",src_ip=SRC_C.."/32",
    dest_ip=MGMT,dest_port="443",proto="tcp",family="ipv4",target="ACCEPT"}
same(fw.snapshot(c,MGMT,"443"),nil,"malformed_existing_rule_refused")

truth(checks>=35,"coverage")
print("AOTT_V3_REMOTE_FIREWALL_PASS checks="..checks)
