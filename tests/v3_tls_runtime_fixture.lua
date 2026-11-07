local root=assert(arg[1],"overlay lua root required")
package.path=root.."/?.lua;"..package.path
package.preload["nixio.fs"]=function() return {} end
package.preload["8311.webutil"]=function() return {} end

local candidate=require "8311.tls_candidate"
local ip=table.concat({"192","0","2","7"},".")
local valid=assert(candidate.validate({
    dns_sans="onu.example.test",
    ip_sans=ip,
    days="365",
    key_type="ec-p256",
}))
assert(#valid.dns==1 and #valid.ips==1)
assert(valid.days=="365" and valid.key_type=="ec-p256")
local bad,why=candidate.validate({
    dns_sans="bad_name.example",
    ip_sans="",
    days="365",
    key_type="ec-p256",
})
assert(bad==nil and why=="Invalid DNS SAN")
bad,why=candidate.validate({
    dns_sans="onu.example.test",
    ip_sans="",
    days="398",
    key_type="ec-p256",
})
assert(bad==nil and why=="TLS validity must be 1 through 397 days")
bad,why=candidate.validate({
    dns_sans="onu.example.test",
    ip_sans="",
    days="365",
    key_type="ec-p384",
})
assert(bad==nil and why=="Unsupported TLS key type")

package.loaded["8311.tls_key_hardener"]=nil
package.preload["nixio.fs"]=function() return {} end
local hardener=require "8311.tls_key_hardener"
local restricted=assert(hardener.evaluate({
    type="reg",uid=0,gid=0,nlink=1,modedec=600
}))
assert(restricted.status=="key_permissions_restricted" and restricted.change_required==false)
local exposed=assert(hardener.evaluate({
    type="reg",uid=0,gid=0,nlink=1,modedec=644
}))
assert(exposed.status=="key_permissions_overexposed" and exposed.change_required==true)
bad,why=hardener.evaluate({
    type="link",uid=0,gid=0,nlink=1,modedec=644
})
assert(bad==nil and why=="unsafe_https_key_inode")
print("AOTT_V3_TLS_RUNTIME_FIXTURE_PASS")
