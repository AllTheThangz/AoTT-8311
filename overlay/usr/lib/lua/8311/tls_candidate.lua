-- AoTT-8311 V3 inactive local TLS candidate generator.
-- Generates only /tmp candidate material. Never changes uhttpd, UCI, /ptconf, or HTTPS.
local fs=require "nixio.fs"
local web=require "8311.webutil"
local M={}
local DIR="/tmp/aott-tls-candidate"
local CERT=DIR.."/candidate.crt.der"
local KEY=DIR.."/candidate.key.der"
local CERT_NEW=CERT..".new"
local KEY_NEW=KEY..".new"
local MAX_CERT=65536
local MAX_KEY=16384

local function dir_ok(st)
    return type(st)=="table" and st.type=="dir" and st.uid==0 and st.gid==0 and st.modedec==700
end
local function file_ok(st,key)
    local maximum=key and MAX_KEY or MAX_CERT
    return type(st)=="table" and st.type=="reg" and st.uid==0 and st.gid==0 and
        st.nlink==1 and type(st.size)=="number" and st.size>=1 and st.size<=maximum and
        st.modedec==(key and 600 or 644)
end
local function same(a,b)
    return a and b and a.dev==b.dev and a.ino==b.ino
end
local function ensure_dir()
    local st=fs.lstat(DIR)
    if not st then
        if fs.mkdir(DIR,700)~=true then return nil,"tls_candidate_directory_create_failed" end
        st=fs.lstat(DIR)
    end
    if not dir_ok(st) then return nil,"tls_candidate_directory_unsafe" end
    return st
end
local function tokens(value)
    if type(value)~="string" or #value>1024 or value:find("[%z\1-\31\127]") then return nil end
    local out={}
    for item in value:gmatch("[^,%s]+") do
        if #out>=4 then return nil end
        out[#out+1]=item
    end
    return out
end
local function dns_name(value)
    if type(value)~="string" or #value<1 or #value>253 then return nil end
    value=value:lower()
    if value:sub(-1)=="." then value=value:sub(1,-2) end
    if #value<1 or #value>253 or value:find("[^a-z0-9%.%-]") or value:find("%.%.") then return nil end
    local count=0
    for label in value:gmatch("[^.]+") do
        count=count+1
        if #label<1 or #label>63 or label:sub(1,1)=="-" or label:sub(-1)=="-" then return nil end
    end
    if count<1 then return nil end
    return value
end
local function ipv4(value)
    if type(value)~="string" or #value<7 or #value>15 or not value:match("^%d+%.%d+%.%d+%.%d+$") then
        return nil
    end
    local out={}
    for part in value:gmatch("%d+") do
        if #part>3 or (#part>1 and part:sub(1,1)=="0") then return nil end
        local n=tonumber(part); if not n or n>255 then return nil end
        out[#out+1]=tostring(n)
    end
    if #out~=4 then return nil end
    local first=tonumber(out[1])
    if first==0 or first>=224 then return nil end
    return table.concat(out,".")
end
local function canonical(form)
    if type(form)~="table" then return nil,"Invalid TLS candidate request" end
    local allowed={dns_sans=true,ip_sans=true,days=true,key_type=true}
    for k,v in pairs(form) do
        if not allowed[k] or type(v)~="string" then return nil,"Unknown TLS candidate field" end
    end
    local dns=tokens(form.dns_sans or ""); local ips=tokens(form.ip_sans or "")
    if not dns or not ips then return nil,"Too many or malformed TLS identities" end
    local seen={}
    for i,value in ipairs(dns) do
        value=dns_name(value); if not value then return nil,"Invalid DNS SAN" end
        local key="dns:"..value; if seen[key] then return nil,"Duplicate TLS identity" end
        seen[key]=true; dns[i]=value
    end
    for i,value in ipairs(ips) do
        value=ipv4(value); if not value then return nil,"Invalid IPv4 SAN" end
        local key="ip:"..value; if seen[key] then return nil,"Duplicate TLS identity" end
        seen[key]=true; ips[i]=value
    end
    if #dns+#ips<1 or #dns+#ips>4 then return nil,"Provide one through four TLS identities" end
    local days=form.days
    if type(days)~="string" or not days:match("^%d+$") or #days>3 or
       tonumber(days)<1 or tonumber(days)>397 or tostring(tonumber(days))~=days then
        return nil,"TLS validity must be 1 through 397 days"
    end
    if form.key_type~="ec-p256" and form.key_type~="rsa-2048" then
        return nil,"Unsupported TLS key type"
    end
    return {dns=dns,ips=ips,days=days,key_type=form.key_type}
end
local function safe_unlink(path,key,stage)
    local st=fs.lstat(path)
    if not st then return true end
    local safe=file_ok(st,key)
    if stage and type(st)=="table" and st.type=="reg" and st.uid==0 and st.gid==0 and
       st.nlink==1 and type(st.size)=="number" and st.size>=1 and
       st.size<=(key and MAX_KEY or MAX_CERT) and
       (st.modedec==600 or st.modedec==644) then
        safe=true
    end
    if not safe then return nil,"unsafe_tls_candidate_file" end
    return fs.unlink(path)==true
end
local function digest_cert()
    local value,why=web.digest(CERT)
    if not value then return nil,why end
    return value
end

function M.validate(form)
    return canonical(form)
end

function M.status()
    local dir=fs.lstat(DIR)
    if not dir then return {status="absent",candidate_ready=false} end
    if not dir_ok(dir) then return nil,"tls_candidate_directory_unsafe" end
    local cert,key=fs.lstat(CERT),fs.lstat(KEY)
    local cert_new,key_new=fs.lstat(CERT_NEW),fs.lstat(KEY_NEW)
    if cert_new or key_new then return nil,"tls_candidate_incomplete_stage" end
    if not cert and not key then return {status="absent",candidate_ready=false} end
    if not file_ok(cert,false) or not file_ok(key,true) then return nil,"tls_candidate_material_unsafe" end
    local fingerprint,why=digest_cert(); if not fingerprint then return nil,why end
    return {
        status="ready",candidate_ready=true,
        certificate_sha256=fingerprint,
        certificate_bytes=cert.size,private_key_bytes=key.size,
        private_key_mode="0600",active_https_changed=false,
        install_available=false,
    }
end

function M.install_material(cert_data,key_data)
    if type(cert_data)~="string" or #cert_data<1 or #cert_data>MAX_CERT or
       type(key_data)~="string" or #key_data<1 or #key_data>MAX_KEY then
        return nil,"TLS import material exceeds candidate limits",422
    end
    local guard=web.lock("/tmp/8311-tls-candidate.lock")
    if not guard then return nil,"TLS candidate operation is busy",409 end
    local function finish(a,b,c) guard:close(); return a,b,c end
    local dir,dir_why=ensure_dir(); if not dir then return finish(nil,dir_why,503) end
    for _,path in ipairs({CERT,KEY,CERT_NEW,KEY_NEW}) do
        if fs.lstat(path) then
            return finish(nil,"Discard the existing TLS candidate before importing another",409)
        end
    end
    local wrote,why=web.write(CERT_NEW,cert_data,644)
    if not wrote then return finish(nil,why or "TLS certificate staging failed",503) end
    wrote,why=web.write(KEY_NEW,key_data,600)
    if not wrote then
        safe_unlink(CERT_NEW,false,true)
        return finish(nil,why or "TLS private-key staging failed",503)
    end
    local cert,key=fs.lstat(CERT_NEW),fs.lstat(KEY_NEW)
    if not file_ok(cert,false) or not file_ok(key,true) or not same(dir,fs.lstat(DIR)) then
        safe_unlink(CERT_NEW,false,true);safe_unlink(KEY_NEW,true,true)
        return finish(nil,"Imported TLS material failed candidate verification",503)
    end
    if fs.rename(KEY_NEW,KEY)~=true or fs.rename(CERT_NEW,CERT)~=true then
        safe_unlink(CERT_NEW,false,true);safe_unlink(KEY_NEW,true,true)
        safe_unlink(KEY,true,false)
        return finish(nil,"Imported TLS material could not enter the inactive candidate slot",503)
    end
    local state,status_why=M.status()
    if not state then return finish(nil,status_why,503) end
    state.imported=true
    return finish(state,nil,200)
end

function M.generate(form)
    local values,why=canonical(form); if not values then return nil,why,422 end
    local guard=web.lock("/tmp/8311-tls-candidate.lock")
    if not guard then return nil,"TLS candidate operation is busy",409 end
    local function finish(a,b,c) guard:close(); return a,b,c end
    local dir,dir_why=ensure_dir(); if not dir then return finish(nil,dir_why,503) end
    for _,path in ipairs({CERT,KEY,CERT_NEW,KEY_NEW}) do
        if fs.lstat(path) then return finish(nil,"Discard the existing TLS candidate before generating another",409) end
    end
    local argv={"/usr/bin/timeout","-k","1","12","/usr/sbin/px5g","selfsigned","-der",
                "-days",values.days,"-newkey"}
    if values.key_type=="ec-p256" then
        argv[#argv+1]="ec";argv[#argv+1]="-pkeyopt";argv[#argv+1]="ec_paramgen_curve:P-256"
    else
        argv[#argv+1]="rsa:2048"
    end
    for _,part in ipairs({"-keyout",KEY_NEW,"-out",CERT_NEW,
                          "-subj","/C=ZZ/O=AoTT/CN=AoTT-8311"}) do argv[#argv+1]=part end
    for _,name in ipairs(values.dns) do
        argv[#argv+1]="-addext";argv[#argv+1]="subjectAltName=DNS:"..name
    end
    for _,address in ipairs(values.ips) do
        argv[#argv+1]="-addext";argv[#argv+1]="subjectAltName=IP:"..address
    end
    local code,_,overflow=web.capture(argv,2048)
    if code~=0 or overflow then
        local k=fs.lstat(KEY_NEW); if k and k.type=="reg" and k.uid==0 and k.nlink==1 then fs.unlink(KEY_NEW) end
        local c=fs.lstat(CERT_NEW); if c and c.type=="reg" and c.uid==0 and c.nlink==1 then fs.unlink(CERT_NEW) end
        return finish(nil,"Vendor TLS candidate generation failed",503)
    end
    if fs.chmod(KEY_NEW,600)~=true or fs.chmod(CERT_NEW,644)~=true then
        return finish(nil,"TLS candidate permission hardening failed",503)
    end
    local key,cert=fs.lstat(KEY_NEW),fs.lstat(CERT_NEW)
    if not file_ok(key,true) or not file_ok(cert,false) or not same(dir,fs.lstat(DIR)) then
        return finish(nil,"TLS candidate material failed verification",503)
    end
    if fs.rename(KEY_NEW,KEY)~=true or fs.rename(CERT_NEW,CERT)~=true then
        return finish(nil,"TLS candidate activation into staging failed",503)
    end
    local state,status_why=M.status()
    if not state then return finish(nil,status_why,503) end
    state.dns_san_count=#values.dns
    state.ipv4_san_count=#values.ips
    state.validity_days=tonumber(values.days)
    state.key_type=values.key_type
    return finish(state,nil,200)
end

function M.discard()
    local guard=web.lock("/tmp/8311-tls-candidate.lock")
    if not guard then return nil,"TLS candidate operation is busy",409 end
    local function finish(a,b,c) guard:close(); return a,b,c end
    local dir=fs.lstat(DIR)
    if not dir then return finish({status="absent",candidate_ready=false},nil,200) end
    if not dir_ok(dir) then return finish(nil,"tls_candidate_directory_unsafe",503) end
    for _,item in ipairs({
        {CERT,false,false},{KEY,true,false},{CERT_NEW,false,true},{KEY_NEW,true,true}
    }) do
        local ok,reason=safe_unlink(item[1],item[2],item[3])
        if not ok then return finish(nil,reason or "TLS candidate cleanup failed",503) end
    end
    if fs.rmdir(DIR)~=true then return finish(nil,"TLS candidate directory cleanup failed",503) end
    return finish({status="discarded",candidate_ready=false},nil,200)
end

M.DIRECTORY=DIR
M.CERTIFICATE= CERT
M.PRIVATE_KEY=KEY
M.MAX_CERT_BYTES=MAX_CERT
M.MAX_KEY_BYTES=MAX_KEY
return M
