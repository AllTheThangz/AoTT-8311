local root=assert(arg[1],"overlay lua root required")
package.path=root.."/?.lua;"..package.path
local guard=require "8311.root_credential_guard"
local hash="$".."6".."$fixture$"..string.rep("A",86)

local ok,why=guard.classify(hash,function(pass,current)
    assert(pass=="root")
    return current
end)
assert(ok==nil and why=="known_factory_root_password")

ok,why=guard.classify(hash,function(pass,current)
    assert(pass=="root")
    return current.."x"
end)
assert(ok==true and why=="unique_password_configured")

for _,bad in ipairs({"","!","*","x","plaintext","$6$short"}) do
    local a,b=guard.classify(bad,function() return "unused" end)
    assert(a==nil and b=="credential_unusable")
end

ok,why=guard.classify(hash,function() error("synthetic crypt failure") end)
assert(ok==nil and why=="credential_check_unavailable")
print("AOTT_ROOT_CREDENTIAL_GUARD_PASS")
