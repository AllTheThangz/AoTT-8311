local root=assert(arg[1],"overlay lua root required")
package.path=root.."/?.lua;"..package.path

local files={
    ["/sys/class/gpio/gpio510/value"]="0\n",
    ["/sys/class/gpio/gpio510/direction"]="out\n",
    ["/sys/class/gpio/gpio508/value"]="1\n",
    ["/sys/class/gpio/gpio508/direction"]="out\n",
}
local ethtool={speed="10000",duplex="full",autoneg="on"}

package.preload["nixio.fs"]=function()
    return {
        lstat=function(path)
            if path=="/sys/class/gpio/gpio510" or path=="/sys/class/gpio/gpio508" then
                return {type="dir",uid=0,gid=0,modedec=755}
            end
            if path=="/dev/sfp_eeprom0" then
                return {type="chr",uid=0,gid=0,modedec=600}
            end
        end,
        readfile=function(path)
            return files[path]
        end,
        writefile=function(path,value)
            if path=="/sys/class/gpio/gpio510/direction" then
                files[path]="out\n"; files["/sys/class/gpio/gpio510/value"]=(value=="high" and "1\n" or "0\n"); return true
            elseif path=="/sys/class/gpio/gpio508/direction" then
                files[path]="out\n"; files["/sys/class/gpio/gpio508/value"]=(value=="high" and "1\n" or "0\n"); return true
            elseif path=="/sys/class/gpio/export" then
                return true
            end
            return false
        end,
    }
end

package.preload["nixio"]=function()
    return {bin={hexlify=function(raw)
        return (raw:gsub(".",function(c) return string.format("%02x",string.byte(c)) end))
    end}}
end

package.preload["8311.webutil"]=function()
    return {capture=function(argv)
        if argv[1]=="/usr/sbin/ethtool" and argv[2]=="-s" then
            for i=4,#argv,2 do ethtool[argv[i]]=argv[i+1] end
            return 0,"",false
        elseif argv[1]=="/usr/sbin/ethtool" and argv[2]=="eth0_0" then
            local out="Settings for eth0_0:\n\tSpeed: "..ethtool.speed.."Mb/s\n\tDuplex: "..(ethtool.duplex=="full" and "Full" or "Half").."\n\tAuto-negotiation: "..(ethtool.autoneg=="on" and "on" or "off").."\n"
            return 0,out,false
        end
        return 1,"",false
    end}
end

local advanced=require "8311.advanced_runtime"
local sfp=require "8311.sfp_runtime"
local checks=0
local function same(a,b,label)
    checks=checks+1
    assert(a==b,"AOTT_RUNTIME_HELPER_FIXTURE:"..label.." expected="..tostring(b).." got="..tostring(a))
end
local function truth(v,label) same(not not v,true,label) end

same(advanced.console(),"0","console_initial")
same(advanced.apply_console("1"),"1","console_apply")
same(advanced.console(),"1","console_readback")
same(advanced.dying(),"0","dying_initial")
same(advanced.apply_dying("1"),"1","dying_apply")
same(advanced.dying(),"1","dying_readback")

local parsed,argv=advanced.parse_ethtool("speed 2500 duplex full autoneg off")
same(parsed.speed,"2500","parse_speed")
same(parsed.duplex,"full","parse_duplex")
same(parsed.autoneg,"off","parse_autoneg")
same(argv[1],"/usr/sbin/ethtool","fixed_ethtool_path")
local applied=assert(advanced.apply_ethtool("speed 2500 duplex full autoneg off"))
truth(applied:find("speed 2500",1,true),"ethtool_apply_canonical")
local ok,observed,source=advanced.ethtool_matches("speed 2500 duplex full autoneg off")
same(ok,true,"ethtool_match")
truth(observed:find("speed 2500",1,true),"ethtool_observed")
same(source,"ethtool_runtime_status","ethtool_source")
same(advanced.parse_ethtool("speed 2500;reboot"),nil,"reject_shellish")
same(advanced.apply_ethtool(""),nil,"clear_live_refused")

local ranges={
    [20]="NEWVENDOR"..string.rep("\0",7),
    [37]=string.char(0x11,0x22,0x33),
    [40]="NEW-PART"..string.rep("\0",8),
    [56]="B2"..string.rep("\0",2),
    [68]="NEWSERIAL"..string.rep("\0",7),
    [84]="261107"..string.rep("\0",2),
    [96]="NEW-DATA"..string.rep("\0",24),
}
local adapter={read_range=function(offset,length)
    local raw=ranges[offset]
    assert(type(raw)=="string" and #raw==length,"bad fixture range "..tostring(offset))
    return raw
end}
local expected={
    sfp_vendor="NEWVENDOR",sfp_oui="11:22:33",sfp_partno="NEW-PART",
    sfp_rev="B2",sfp_serial="NEWSERIAL",sfp_date="261107",
    sfp_vendordata="NEW-DATA",
}
for id,want in pairs(expected) do
    local value=assert(sfp.read(id,adapter))
    same(value,want,"sfp_read_"..id)
    local match,actual,src=sfp.matches(id,want,adapter)
    same(match,true,"sfp_match_"..id)
    same(actual,want,"sfp_actual_"..id)
    same(src,"virtual_sfp_eeprom","sfp_source_"..id)
end
same(sfp.read("unknown",adapter),nil,"unknown_sfp_refused")
truth(checks>=40,"coverage")
print("AOTT_V3_RUNTIME_HELPERS_PASS checks="..checks)
