-- AoTT-8311 V3 operator-owned TLS import.
-- Bounded multipart staging, local PEM/DER inspection, and native uhttpd
-- load/handshake verification. This module never activates HTTPS itself.
local nixio=require "nixio"
local fs=require "nixio.fs"
local web=require "8311.webutil"
local candidate=require "8311.tls_candidate"
local M={}

local MAX_LEAF=16384
local MAX_KEY=16384
local MAX_CHAIN=49152
local MAX_TOTAL=MAX_LEAF+MAX_KEY+MAX_CHAIN+32768
local MAX_CHAIN_CERTS=3
local ROOT_PREFIX="/tmp/aott-tls-import-"
local LOOPBACK="127"..".0.0.1"
local CERT_LABEL="CERTIFICATE"
local KEY_LABELS={["PRIVATE KEY"]=true,["RSA PRIVATE KEY"]=true,["EC PRIVATE KEY"]=true}

local function clean_tokens(value,kind)
    if type(value)~="string" or #value>1024 or value:find("[%z\1-\31\127]") then return nil end
    local out,seen={},{}
    for token in value:gmatch("[^,%s]+") do
        if #out>=8 then return nil end
        if kind=="dns" then
            token=token:lower()
            if token:sub(-1)=="." then token=token:sub(1,-2) end
            if #token<1 or #token>253 or token:find("[^a-z0-9.*%-]") or token:find("%.%.") then return nil end
            if token:find("%*") then
                if not token:match("^%*%.[a-z0-9][a-z0-9.-]+$") or token:find("%*",2,true) then return nil end
            end
            for label in token:gmatch("[^.]+") do
                if label~="*" and (#label<1 or #label>63 or label:sub(1,1)=="-" or label:sub(-1)=="-") then return nil end
            end
        else
            local parts={}
            local a,b,c,d=token:match("^(%d+)%.(%d+)%.(%d+)%.(%d+)$")
            if not a then return nil end
            for _,v in ipairs({a,b,c,d}) do
                if #v>3 or (#v>1 and v:sub(1,1)=="0") or tonumber(v)>255 then return nil end
                parts[#parts+1]=tostring(tonumber(v))
            end
            token=table.concat(parts,".")
            local first=tonumber(parts[1])
            if first==0 or first>=224 then return nil end
        end
        local key=kind..":"..token
        if seen[key] then return nil end
        seen[key]=true;out[#out+1]=token
    end
    return out
end

local function pem_marker(label,ending)
    return "-----"..(ending and "END " or "BEGIN ")..label.."-----"
end

local function b64_der(block,label)
    local begin=pem_marker(label,false)
    local finish=pem_marker(label,true)
    local pattern="^%s*"..begin:gsub("%-","%%-").."%s*([A-Za-z0-9+/=%s]+)%s*"..
        finish:gsub("%-","%%-").."%s*$"
    local body=block:match(pattern)
    if not body then return nil,"invalid_pem_structure" end
    body=body:gsub("%s","")
    if #body<4 or #body%4~=0 or body:find("[^A-Za-z0-9+/=]") or
       body:find("=[^=]") then return nil,"invalid_pem_base64" end
    local der=nixio.bin.b64decode(body)
    if type(der)~="string" or #der<3 then return nil,"pem_decode_failed" end
    local check=nixio.bin.b64encode(der)
    if type(check)~="string" or check:gsub("=","")~=body:gsub("=","") then
        return nil,"pem_decode_roundtrip_failed"
    end
    return der
end

local function pem_wrap(label,der)
    local b64=nixio.bin.b64encode(der)
    if type(b64)~="string" then return nil end
    local lines={}
    for i=1,#b64,64 do lines[#lines+1]=b64:sub(i,i+63) end
    return pem_marker(label,false).."\n"..table.concat(lines,"\n").."\n"..pem_marker(label,true).."\n"
end

local function der_tlv(data,pos,limit)
    pos=pos or 1;limit=limit or #data
    if pos>limit or pos>#data then return nil,"der_truncated" end
    local tag=data:byte(pos); if not tag then return nil,"der_truncated" end
    local lb=data:byte(pos+1); if not lb then return nil,"der_truncated" end
    local len,head
    if lb<128 then len=lb;head=2
    else
        local width=lb-128
        if width<1 or width>4 or pos+1+width>limit then return nil,"der_length_invalid" end
        len=0
        for i=1,width do
            local b=data:byte(pos+1+i)
            if i==1 and b==0 then return nil,"der_length_noncanonical" end
            len=len*256+b
        end
        if len<128 then return nil,"der_length_noncanonical" end
        head=2+width
    end
    local first=pos+head
    local last=first+len-1
    if last>limit or last>#data then return nil,"der_truncated" end
    return {tag=tag,start=pos,content=first,last=last,next=last+1,length=len}
end

local function children(data,node)
    local out,pos={},node.content
    while pos<=node.last do
        local child,why=der_tlv(data,pos,node.last)
        if not child then return nil,why end
        out[#out+1]=child
        if #out>256 then return nil,"der_too_many_children" end
        pos=child.next
    end
    if pos~=node.last+1 then return nil,"der_child_boundary_invalid" end
    return out
end

local function raw_node(data,node)
    return data:sub(node.start,node.next-1)
end

local function canonical_time(tag,value)
    if tag==0x17 then
        local yy,mo,dd,hh,mi,ss=value:match("^(%d%d)(%d%d)(%d%d)(%d%d)(%d%d)(%d%d)Z$")
        if not yy then
            yy,mo,dd,hh,mi=value:match("^(%d%d)(%d%d)(%d%d)(%d%d)(%d%d)Z$")
            ss="00"
        end
        if not yy then return nil end
        local year=tonumber(yy)>=50 and ("19"..yy) or ("20"..yy)
        return year..mo..dd..hh..mi..ss.."Z"
    elseif tag==0x18 then
        local y,mo,dd,hh,mi,ss=value:match("^(%d%d%d%d)(%d%d)(%d%d)(%d%d)(%d%d)(%d%d)Z$")
        if not y then return nil end
        return y..mo..dd..hh..mi..ss.."Z"
    end
end

local function oid_is(data,node,bytes)
    return node and node.tag==0x06 and data:sub(node.content,node.last)==bytes
end

local OID_SAN=string.char(0x55,0x1d,0x11)
local OID_BASIC=string.char(0x55,0x1d,0x13)
local OID_KEY_USAGE=string.char(0x55,0x1d,0x0f)
local OID_NAME_CONSTRAINTS=string.char(0x55,0x1d,0x1e)
local OID_EKU=string.char(0x55,0x1d,0x25)
local OID_SERVER_AUTH=string.char(0x2b,0x06,0x01,0x05,0x05,0x07,0x03,0x01)
local OID_RSA=string.char(0x2a,0x86,0x48,0x86,0xf7,0x0d,0x01,0x01,0x01)
local OID_EC=string.char(0x2a,0x86,0x48,0xce,0x3d,0x02,0x01)
local OID_P256=string.char(0x2a,0x86,0x48,0xce,0x3d,0x03,0x01,0x07)
local OID_P384=string.char(0x2b,0x81,0x04,0x00,0x22)
local APPROVED_SIGNATURES={
    [string.char(0x2a,0x86,0x48,0x86,0xf7,0x0d,0x01,0x01,0x0b)]=true,
    [string.char(0x2a,0x86,0x48,0x86,0xf7,0x0d,0x01,0x01,0x0c)]=true,
    [string.char(0x2a,0x86,0x48,0x86,0xf7,0x0d,0x01,0x01,0x0d)]=true,
    [string.char(0x2a,0x86,0x48,0xce,0x3d,0x04,0x03,0x02)]=true,
    [string.char(0x2a,0x86,0x48,0xce,0x3d,0x04,0x03,0x03)]=true,
    [string.char(0x2a,0x86,0x48,0xce,0x3d,0x04,0x03,0x04)]=true,
}

local function algorithm_oid(data,node)
    if not node or node.tag~=0x30 then return nil end
    local parts=children(data,node)
    if type(parts)~="table" or not parts[1] or parts[1].tag~=0x06 then return nil end
    return data:sub(parts[1].content,parts[1].last),parts
end

local function approved_signature(data,node)
    local oid=algorithm_oid(data,node)
    return oid and APPROVED_SIGNATURES[oid] or false
end

local function integer_bits(raw)
    if type(raw)~="string" or #raw<1 then return nil end
    if raw:byte(1)==0 then raw=raw:sub(2) end
    if #raw<1 then return nil end
    local first=raw:byte(1)
    local top=0
    while first>0 do top=top+1;first=math.floor(first/2) end
    return (#raw-1)*8+top
end

local function spki_policy(data,node)
    local parts=children(data,node)
    if type(parts)~="table" or #parts~=2 or parts[1].tag~=0x30 or parts[2].tag~=0x03 then
        return nil,"public_key_structure_invalid"
    end
    local oid,alg=algorithm_oid(data,parts[1])
    if not oid then return nil,"public_key_algorithm_invalid" end
    local bit=parts[2]
    if bit.length<2 or data:byte(bit.content)~=0 then return nil,"public_key_bitstring_invalid" end
    local key=data:sub(bit.content+1,bit.last)
    if oid==OID_RSA then
        local seq=der_tlv(key,1,#key)
        if not seq or seq.tag~=0x30 or seq.next~=#key+1 then return nil,"rsa_public_key_invalid" end
        local vals=children(key,seq)
        if type(vals)~="table" or #vals~=2 or vals[1].tag~=0x02 or vals[2].tag~=0x02 then
            return nil,"rsa_public_key_invalid"
        end
        local bits=integer_bits(key:sub(vals[1].content,vals[1].last))
        if not bits or bits<2048 or bits>4096 then return nil,"rsa_key_size_refused" end
        return {algorithm="rsa",bits=bits}
    elseif oid==OID_EC then
        if not alg[2] or alg[2].tag~=0x06 then return nil,"ec_curve_missing" end
        local curve=data:sub(alg[2].content,alg[2].last)
        if curve==OID_P256 and #key==65 then return {algorithm="ec",curve="P-256"} end
        if curve==OID_P384 and #key==97 then return {algorithm="ec",curve="P-384"} end
        return nil,"ec_curve_refused"
    end
    return nil,"public_key_algorithm_refused"
end

local function parse_extensions(data,node)
    local result={dns={},ips={},san_present=false,basic_present=false,ca=nil,
        basic_path_length=nil,eku_server=nil,key_usage_present=false,
        digital_signature=nil,key_cert_sign=nil}
    if not node then return result end
    local outer,why=children(data,node); if not outer or #outer~=1 or outer[1].tag~=0x30 then
        return nil,why or "extensions_container_invalid"
    end
    local extlist;extlist,why=children(data,outer[1]);if not extlist then return nil,why end
    for _,ext in ipairs(extlist) do
        if ext.tag~=0x30 then return nil,"extension_record_invalid" end
        local parts;parts,why=children(data,ext);if not parts or #parts<2 or #parts>3 then return nil,why or "extension_record_invalid" end
        local value=parts[#parts]
        if value.tag~=0x04 then return nil,"extension_value_missing" end
        local oid=parts[1]
        local inner=data:sub(value.content,value.last)
        if oid_is(data,oid,OID_SAN) then
            result.san_present=true
            local seq,ewhy=der_tlv(inner,1,#inner)
            if not seq or seq.tag~=0x30 or seq.next~=#inner+1 then return nil,ewhy or "san_extension_invalid" end
            local names
            names,ewhy=children(inner,seq);if not names then return nil,ewhy end
            for _,name in ipairs(names) do
                if name.tag==0x82 then
                    local dns=inner:sub(name.content,name.last):lower()
                    if #dns<1 or #dns>253 or dns:find("[^a-z0-9.*%-]") then return nil,"san_dns_invalid" end
                    result.dns[#result.dns+1]=dns
                elseif name.tag==0x87 then
                    local raw=inner:sub(name.content,name.last)
                    if #raw==4 then
                        result.ips[#result.ips+1]=table.concat({raw:byte(1),raw:byte(2),raw:byte(3),raw:byte(4)},".")
                    end
                end
            end
        elseif oid_is(data,oid,OID_BASIC) then
            result.basic_present=true
            local seq,ewhy=der_tlv(inner,1,#inner)
            if not seq or seq.tag~=0x30 or seq.next~=#inner+1 then return nil,ewhy or "basic_constraints_invalid" end
            local vals;vals,ewhy=children(inner,seq);if not vals then return nil,ewhy end
            result.ca=false
            local offset=1
            if vals[1] and vals[1].tag==0x01 then
                local b=inner:byte(vals[1].content)
                result.ca=b~=0
                offset=2
            end
            if vals[offset] and vals[offset].tag==0x02 then
                local raw=inner:sub(vals[offset].content,vals[offset].last)
                if #raw<1 or #raw>4 or raw:byte(1)>=128 then return nil,"basic_path_length_invalid" end
                local n=0
                for i=1,#raw do n=n*256+raw:byte(i) end
                result.basic_path_length=n
            end
        elseif oid_is(data,oid,OID_KEY_USAGE) then
            result.key_usage_present=true
            local bits,ewhy=der_tlv(inner,1,#inner)
            if not bits or bits.tag~=0x03 or bits.next~=#inner+1 or bits.length<2 then
                return nil,ewhy or "key_usage_invalid"
            end
            local unused=inner:byte(bits.content)
            local first=inner:byte(bits.content+1)
            if not unused or unused>7 or not first then return nil,"key_usage_invalid" end
            result.digital_signature=math.floor(first/128)%2==1
            result.key_cert_sign=math.floor(first/4)%2==1
        elseif oid_is(data,oid,OID_NAME_CONSTRAINTS) then
            return nil,"name_constraints_unsupported"
        elseif oid_is(data,oid,OID_EKU) then
            result.eku_server=inner:find(OID_SERVER_AUTH,1,true)~=nil
        end
    end
    table.sort(result.dns);table.sort(result.ips)
    return result
end

local function parse_certificate(der)
    if type(der)~="string" or #der<128 or #der>MAX_LEAF then return nil,"certificate_size_refused" end
    local top,why=der_tlv(der,1,#der)
    if not top or top.tag~=0x30 or top.next~=#der+1 then return nil,why or "certificate_der_invalid" end
    local cert;cert,why=children(der,top)
    if not cert or #cert~=3 or cert[1].tag~=0x30 then return nil,why or "certificate_structure_invalid" end
    local tbs; tbs,why=children(der,cert[1]);if not tbs then return nil,why end
    local i=1
    if tbs[i] and tbs[i].tag==0xa0 then i=i+1 end
    local serial=tbs[i];local signature=tbs[i+1];local issuer=tbs[i+2]
    local validity=tbs[i+3];local subject=tbs[i+4];local spki=tbs[i+5]
    if not serial or not signature or not issuer or not validity or validity.tag~=0x30 or
       not subject or not spki or spki.tag~=0x30 then return nil,"certificate_tbs_invalid" end
    if not approved_signature(der,signature) or not approved_signature(der,cert[2]) then
        return nil,"certificate_signature_algorithm_refused"
    end
    local public_key,key_why=spki_policy(der,spki)
    if not public_key then return nil,key_why end
    local times;times,why=children(der,validity)
    if not times or #times~=2 then return nil,why or "certificate_validity_invalid" end
    local before=canonical_time(times[1].tag,der:sub(times[1].content,times[1].last))
    local after=canonical_time(times[2].tag,der:sub(times[2].content,times[2].last))
    if not before or not after or before>=after then return nil,"certificate_validity_invalid" end
    local extensions=nil
    for index=i+6,#tbs do if tbs[index].tag==0xa3 then extensions=tbs[index];break end end
    local ext;ext,why=parse_extensions(der,extensions);if not ext then return nil,why end
    if not ext.san_present then return nil,"certificate_san_required" end
    if not ext.basic_present or ext.ca~=false then return nil,"leaf_basic_constraints_invalid" end
    if ext.eku_server==false then return nil,"leaf_server_auth_eku_required" end
    if ext.key_usage_present and ext.digital_signature~=true then
        return nil,"leaf_digital_signature_key_usage_required"
    end
    return {
        der=der,not_before=before,not_after=after,dns=ext.dns,ips=ext.ips,
        issuer=raw_node(der,issuer),subject=raw_node(der,subject),
        self_signed_name=raw_node(der,issuer)==raw_node(der,subject),
        ca=ext.ca,public_key=public_key,
    }
end

local function parse_ca_certificate(der)
    local leaf,why=parse_certificate(der)
    if leaf then return nil,"chain_certificate_cannot_be_leaf" end
    -- CA certificates need a relaxed extension pass but the same outer/tbs shape.
    local top=der_tlv(der,1,#der)
    if not top or top.tag~=0x30 or top.next~=#der+1 then return nil,"chain_certificate_der_invalid" end
    local cert=children(der,top)
    if type(cert)~="table" or #cert~=3 or cert[1].tag~=0x30 then return nil,"chain_certificate_structure_invalid" end
    local tbs=children(der,cert[1]);if type(tbs)~="table" then return nil,"chain_certificate_tbs_invalid" end
    local i=1;if tbs[i] and tbs[i].tag==0xa0 then i=i+1 end
    local signature=tbs[i+1];local issuer=tbs[i+2];local validity=tbs[i+3]
    local subject=tbs[i+4];local spki=tbs[i+5]
    if not signature or not issuer or not validity or validity.tag~=0x30 or
       not subject or not spki or spki.tag~=0x30 then return nil,"chain_certificate_tbs_invalid" end
    if not approved_signature(der,signature) or not approved_signature(der,cert[2]) then
        return nil,"chain_signature_algorithm_refused"
    end
    local public_key,key_why=spki_policy(der,spki)
    if not public_key then return nil,key_why end
    local times=children(der,validity);if type(times)~="table" or #times~=2 then return nil,"chain_certificate_validity_invalid" end
    local before=canonical_time(times[1].tag,der:sub(times[1].content,times[1].last))
    local after=canonical_time(times[2].tag,der:sub(times[2].content,times[2].last))
    if not before or not after or before>=after then return nil,"chain_certificate_validity_invalid" end
    local extensions=nil
    for index=i+6,#tbs do if tbs[index].tag==0xa3 then extensions=tbs[index];break end end
    local ext=parse_extensions(der,extensions)
    if not ext or not ext.basic_present or ext.ca~=true then return nil,"chain_certificate_not_ca" end
    if ext.key_usage_present and ext.key_cert_sign~=true then
        return nil,"chain_key_cert_sign_required"
    end
    return {der=der,not_before=before,not_after=after,
        issuer=raw_node(der,issuer),subject=raw_node(der,subject),
        self_signed_name=raw_node(der,issuer)==raw_node(der,subject),ca=true,
        path_length=ext.basic_path_length,public_key=public_key}
end

local function now_utc()
    return os.date("!%Y%m%d%H%M%SZ")
end

local function identity_matches(pattern,name)
    if pattern==name then return true end
    if pattern:sub(1,2)=="*." and pattern:sub(3):find("*",1,true)==nil then
        local suffix=pattern:sub(3)
        if suffix:find("%.") and name:sub(-( #suffix+1))=="."..suffix then
            local prefix=name:sub(1,-(#suffix+2))
            return prefix~="" and not prefix:find("%.")
        end
    end
    return false
end

local function inspect_material(leaf_bytes,key_bytes,chain_bytes,dns_required,ips_required)
    if type(leaf_bytes)~="string" or #leaf_bytes<1 or #leaf_bytes>MAX_LEAF or
       type(key_bytes)~="string" or #key_bytes<1 or #key_bytes>MAX_KEY or
       type(chain_bytes)~="string" or #chain_bytes>MAX_CHAIN then
        return nil,"tls_import_size_refused"
    end
    local leaf_der,leaf_pem
    if leaf_bytes:match("^%s*%-%-%-%-%-BEGIN CERTIFICATE%-%-%-%-%-") then
        leaf_der=select(1,b64_der(leaf_bytes,CERT_LABEL))
        if not leaf_der then return nil,"tls_leaf_pem_invalid" end
        leaf_pem=pem_wrap(CERT_LABEL,leaf_der)
    else
        leaf_der=leaf_bytes;leaf_pem=pem_wrap(CERT_LABEL,leaf_der)
    end
    if not leaf_pem then return nil,"tls_leaf_normalization_failed" end
    local leaf,why=parse_certificate(leaf_der);if not leaf then return nil,why end
    local now=now_utc()
    if leaf.not_before>now or leaf.not_after<=now then return nil,"certificate_not_current" end

    local key_out=key_bytes
    if key_bytes:match("^%s*%-%-%-%-%-BEGIN ") then
        local label=key_bytes:match("^%s*%-%-%-%-%-BEGIN ([A-Z ]+)%-%-%-%-%-")
        if not label or not KEY_LABELS[label] then return nil,"private_key_pem_type_refused" end
        local der,key_why=b64_der(key_bytes,label)
        if not der then return nil,key_why or "private_key_pem_invalid" end
        local root=der_tlv(der,1,#der)
        if not root or root.tag~=0x30 or root.next~=#der+1 then return nil,"private_key_der_invalid" end
    else
        local root=der_tlv(key_bytes,1,#key_bytes)
        if not root or root.tag~=0x30 or root.next~=#key_bytes+1 then return nil,"private_key_der_invalid" end
    end

    local chain_pem=""
    local chain={}
    if chain_bytes~="" then
        if chain_bytes:find(pem_marker(CERT_LABEL,false),1,true) then
            local pos=1
            while true do
                local b,e=chain_bytes:find(pem_marker(CERT_LABEL,false),pos,true)
                if not b then
                    if chain_bytes:sub(pos):match("%S") then return nil,"chain_extra_material_refused" end
                    break
                end
                if chain_bytes:sub(pos,b-1):match("%S") then return nil,"chain_extra_material_refused" end
                local eb,ee=chain_bytes:find(pem_marker(CERT_LABEL,true),e+1,true)
                if not eb then return nil,"chain_pem_unterminated" end
                local block=chain_bytes:sub(b,ee)
                local der=b64_der(block,CERT_LABEL)
                if not der then return nil,"chain_pem_invalid" end
                chain[#chain+1]=der
                if #chain>MAX_CHAIN_CERTS then return nil,"chain_too_long" end
                pos=ee+1
            end
        else
            chain[1]=chain_bytes
        end
    end

    local parsed_chain={}
    for i,der in ipairs(chain) do
        local ca,ca_why=parse_ca_certificate(der)
        if not ca then return nil,ca_why end
        if ca.not_before>now or ca.not_after<=now then return nil,"chain_certificate_not_current" end
        if ca.path_length~=nil and ca.path_length<(i-1) then
            return nil,"chain_path_length_exceeded"
        end
        parsed_chain[i]=ca
    end

    local anchor_supplied=false
    if leaf.self_signed_name then
        if #parsed_chain>0 then return nil,"self_signed_leaf_must_not_include_chain" end
    else
        if #parsed_chain<1 then return nil,"issuer_chain_required" end
        if leaf.issuer~=parsed_chain[1].subject then return nil,"chain_issuer_name_mismatch" end
        for i=1,#parsed_chain-1 do
            if parsed_chain[i].issuer~=parsed_chain[i+1].subject then
                return nil,"chain_issuer_name_mismatch"
            end
        end
        anchor_supplied=parsed_chain[#parsed_chain].self_signed_name==true
    end
    local serve_count=#parsed_chain
    if anchor_supplied then serve_count=serve_count-1 end
    for i=1,serve_count do
        local pem=pem_wrap(CERT_LABEL,parsed_chain[i].der)
        if not pem then return nil,"chain_normalization_failed" end
        chain_pem=chain_pem..pem
    end

    for _,name in ipairs(dns_required or {}) do
        local found=false
        for _,pattern in ipairs(leaf.dns) do if identity_matches(pattern,name) then found=true;break end end
        if not found then return nil,"expected_dns_not_in_san" end
    end
    local ips={}
    for _,ip in ipairs(leaf.ips) do ips[ip]=true end
    for _,ip in ipairs(ips_required or {}) do if not ips[ip] then return nil,"expected_ip_not_in_san" end end

    return {
        cert_bundle=leaf_pem..chain_pem,key_data=key_out,
        certificate_sha256=nil,expires_utc=leaf.not_after,
        dns_san_count=#leaf.dns,ip_san_count=#leaf.ips,
        chain_certificates=#parsed_chain,
        chain_name_links_verified=#parsed_chain,
        trust_anchor_supplied=anchor_supplied,
        chain_signature_verification="browser_confirmation_required",
        public_key_algorithm=leaf.public_key.algorithm,
        public_key_strength=leaf.public_key.bits or leaf.public_key.curve,
        browser_trust_unverified=true,
    }
end

local function private_file(path,max,mode)
    local st=fs.lstat(path)
    return st and st.type=="reg" and st.uid==0 and st.gid==0 and st.nlink==1 and
        st.modedec==mode and type(st.size)=="number" and st.size>=1 and st.size<=max and st
end

local function cleanup(dir)
    if type(dir)~="string" or not dir:match("^/tmp/aott%-tls%-import%-%x+$") then return false end
    for _,name in ipairs({"leaf","key","chain","probe-index","cert-probe","key-probe"}) do
        local p=dir.."/"..name
        local st=fs.lstat(p)
        if st and st.type=="reg" and st.uid==0 and st.nlink==1 then fs.unlink(p) end
    end
    return fs.rmdir(dir)==true
end

local function probe_pair(cert_path,key_path,dir)
    if not private_file(cert_path,MAX_LEAF+MAX_CHAIN,600) or not private_file(key_path,MAX_KEY,600) then
        return nil,"tls_probe_material_unsafe"
    end
    local index=dir.."/probe-index"
    local ok,why=web.write(index,"AOTT-TLS-IMPORT-PROBE\n",600)
    if not ok then return nil,why end
    local base=42000+(nixio.getpid()%10000)
    for attempt=0,3 do
        local port=base+attempt
        local pid=nixio.fork()
        if not pid then return nil,"tls_probe_fork_failed" end
        if pid==0 then
            local null=nixio.open("/dev/null",nixio.open_flags("rdwr"))
            if null then nixio.dup(null,nixio.stdin);nixio.dup(null,nixio.stdout);nixio.dup(null,nixio.stderr);null:close() end
            nixio.exec("/usr/sbin/uhttpd","-f","-h",dir,"-s",LOOPBACK..":"..tostring(port),
                "-C",cert_path,"-K",key_path,"-T","3","-N","2","-n","1")
            os.exit(127)
        end
        nixio.nanosleep(0,350000000)
        local code,out,overflow=web.capture({"/bin/uclient-fetch","--no-check-certificate","--timeout=3",
            "-q","-O","-","https://"..LOOPBACK..":"..tostring(port).."/probe-index"},256)
        nixio.kill(pid,nixio.const.SIGTERM)
        nixio.waitpid(pid)
        if code==0 and not overflow and out=="AOTT-TLS-IMPORT-PROBE\n" then
            fs.unlink(index)
            return true
        end
    end
    fs.unlink(index)
    return nil,"tls_native_pair_handshake_failed"
end

function M.inspect_bytes(leaf,key,chain,dns_text,ip_text)
    local dns=clean_tokens(dns_text or "","dns")
    local ips=clean_tokens(ip_text or "","ip")
    if not dns or not ips or #dns+#ips<1 then return nil,"Provide at least one valid DNS or IPv4 identity" end
    return inspect_material(leaf,key,chain or "",dns,ips)
end

function M.receive(http,owner)
    if type(owner)~="string" or owner=="" then return nil,"Authenticated session required",403 end
    if not (http.getenv("CONTENT_TYPE") or ""):match("^multipart/form%-data[; ]") then
        return nil,"Use multipart certificate import",415
    end
    local existing,existing_why=candidate.status()
    if not existing then return nil,existing_why or "TLS candidate state unavailable",503 end
    if existing.candidate_ready then return nil,"Discard the existing TLS candidate before importing another",409 end
    local dir,id=web.private_dir(ROOT_PREFIX)
    if not dir then return nil,id,507 end
    if not http.setbodylimit(MAX_TOTAL) then cleanup(dir);return nil,"Upload body was already parsed",400 end
    local spec={
        certificate_file={name="leaf",max=MAX_LEAF,required=true},
        private_key_file={name="key",max=MAX_KEY,required=true},
        chain_file={name="chain",max=MAX_CHAIN,required=false},
    }
    local handles,bytes,complete={}, {}, {}
    local failure,failure_code
    local function reject(msg,code) failure=msg;failure_code=code;return false,msg end
    http.setfilehandler(function(meta,chunk,eof)
        if failure then return false,failure end
        local rule=meta and spec[meta.name]
        if not rule or type(meta.file)~="string" then return reject("Unexpected TLS import file part",400) end
        if complete[meta.name] then return reject("Duplicate TLS import file part",400) end
        if not handles[meta.name] then
            handles[meta.name]=io.open(dir.."/"..rule.name,"wb")
            if not handles[meta.name] then return reject("Unable to stage TLS import material",507) end
            bytes[meta.name]=0
        end
        if chunk and #chunk>0 then
            bytes[meta.name]=bytes[meta.name]+#chunk
            if bytes[meta.name]>rule.max then return reject("TLS import file exceeds size limit",413) end
            if not handles[meta.name]:write(chunk) then return reject("TLS import write failed",507) end
        end
        if eof then
            local closed=handles[meta.name]:close();handles[meta.name]=nil
            if not closed then return reject("TLS import close failed",507) end
            complete[meta.name]=true
        end
        return true
    end)
    local values=http.formvalue()
    local parse_error,parse_code=http.inputerror()
    for _,h in pairs(handles) do pcall(function()h:close()end) end
    if parse_error or failure then cleanup(dir);return nil,failure or parse_error,failure_code or parse_code or 400 end
    if type(values)~="table" then cleanup(dir);return nil,"TLS import form unavailable",400 end
    for name,value in pairs(values) do
        if name~="dns_sans" and name~="ip_sans" and name~="token" and not spec[name] then
            cleanup(dir);return nil,"Unexpected TLS import field",400
        end
        if type(value)~="string" then cleanup(dir);return nil,"Duplicate TLS import field",400 end
    end
    for name,rule in pairs(spec) do
        if rule.required and (not complete[name] or not bytes[name] or bytes[name]<1) then
            cleanup(dir);return nil,"Certificate and private key are required",422
        end
    end
    for name,rule in pairs(spec) do
        local path=dir.."/"..rule.name
        if complete[name] then
            if fs.chmod(path,600)~=true or not private_file(path,rule.max,600) then
                cleanup(dir);return nil,"TLS import staged file failed verification",503
            end
        end
    end
    local leaf=fs.readfile(dir.."/leaf",MAX_LEAF+1)
    local key=fs.readfile(dir.."/key",MAX_KEY+1)
    local chain=complete.chain_file and fs.readfile(dir.."/chain",MAX_CHAIN+1) or ""
    local inspected,why=M.inspect_bytes(leaf,key,chain,values.dns_sans or "",values.ip_sans or "")
    if not inspected then cleanup(dir);return nil,why,422 end
    local cert_probe=dir.."/cert-probe"
    local key_probe=dir.."/key-probe"
    if not web.write(cert_probe,inspected.cert_bundle,600) or not web.write(key_probe,inspected.key_data,600) then
        cleanup(dir);return nil,"TLS import probe staging failed",503
    end
    local pair,pair_why=probe_pair(cert_probe,key_probe,dir)
    fs.unlink(cert_probe);fs.unlink(key_probe)
    if not pair then cleanup(dir);return nil,pair_why,422 end
    local state,install_why,status=candidate.install_material(inspected.cert_bundle,inspected.key_data)
    if not state then cleanup(dir);return nil,install_why,status or 503 end
    cleanup(dir)
    return {
        status="TLS_IMPORT_CANDIDATE_READY",candidate_ready=true,
        certificate_sha256=state.certificate_sha256,
        certificate_bytes=state.certificate_bytes,
        private_key_bytes=state.private_key_bytes,
        private_key_mode=state.private_key_mode,
        expires_utc=inspected.expires_utc,
        dns_san_count=inspected.dns_san_count,
        ipv4_san_count=inspected.ip_san_count,
        chain_certificates=inspected.chain_certificates,
        native_uhttpd_pair_verified=true,
        chain_name_links_verified=inspected.chain_name_links_verified,
        browser_trust_unverified=true,
        active_https_changed=false,
    },nil,201
end

M.MAX_LEAF_BYTES=MAX_LEAF
M.MAX_KEY_BYTES=MAX_KEY
M.MAX_CHAIN_BYTES=MAX_CHAIN
return M
