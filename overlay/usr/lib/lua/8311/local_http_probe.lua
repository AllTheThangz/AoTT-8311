-- AoTT-8311 V3 bounded local HTTP behavior probe.
-- Connects only to a validated IPv4 address supplied by trusted management
-- configuration and reads only the HTTP response headers.
local nixio=require "nixio"
local M={}

local function ipv4(value)
    if type(value)~="string" or #value>15 then return nil end
    local a,b,c,d=value:match("^(%d+)%.(%d+)%.(%d+)%.(%d+)$")
    if not a then return nil end
    for _,part in ipairs({a,b,c,d}) do
        if #part>3 or (#part>1 and part:sub(1,1)=="0") or tonumber(part)>255 then
            return nil
        end
    end
    return value
end

local function poll(fd,kinds,timeout)
    local row={fd=fd,events=nixio.poll_flags(unpack(kinds))}
    local count=nixio.poll({row},timeout)
    return type(count)=="number" and count>0 and type(row.revents)=="number" and row.revents>0
end

function M.inspect(address)
    address=ipv4(address)
    if not address then return nil,"invalid_management_ipv4" end
    local sock=nixio.connect(address,80)
    if not sock then return nil,"http_connect_failed" end
    sock:setblocking(false)
    local request="GET / HTTP/1.0\r\nHost: "..address..
        "\r\nConnection: close\r\n\r\n"
    local sent=0
    for _=1,25 do
        if sent>=#request then break end
        local wrote=sock:write(request:sub(sent+1))
        if type(wrote)=="number" and wrote>0 then
            sent=sent+wrote
        elseif not poll(sock,{"out","err","hup"},100) then
            -- bounded retry
        end
    end
    if sent~=#request then sock:close(); return nil,"http_request_write_failed" end

    local chunks,total={},0
    for _=1,30 do
        local part=sock:read(1024)
        if type(part)=="string" and #part>0 then
            total=total+#part
            if total>4096 then sock:close(); return nil,"http_headers_too_large" end
            chunks[#chunks+1]=part
            if table.concat(chunks):find("\r\n\r\n",1,true) then break end
        elseif part=="" then
            break
        else
            poll(sock,{"in","err","hup"},100)
        end
    end
    sock:close()
    local raw=table.concat(chunks)
    local header=raw:match("^(.-\r\n\r\n)")
    if not header then return nil,"http_header_incomplete" end
    local code=tonumber(header:match("^HTTP/%d+%.%d+%s+(%d%d%d)%s"))
    if not code then return nil,"http_status_invalid" end
    local location
    for line in header:gmatch("[^\r\n]+") do
        local key,value=line:match("^([^:]+):%s*(.-)%s*$")
        if key and key:lower()=="location" then location=value end
    end
    local redirect=code==301 or code==302 or code==303 or code==307 or code==308
    local redirects_https=redirect and type(location)=="string" and
        location:lower():match("^https://")~=nil
    return {
        status=code,
        redirects_https=redirects_https,
        response_checked=true,
    }
end

M.valid_ipv4=ipv4
return M
