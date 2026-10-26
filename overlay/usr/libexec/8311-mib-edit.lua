#!/usr/bin/lua
local function die(msg)
    io.stderr:write("8311-mib-edit: " .. msg .. "\n")
    os.exit(1)
end

local function tokenize(line)
    local tokens, spans, i, n = {}, {}, 1, #line
    local comment
    while i <= n do
        while i <= n and line:sub(i,i):match("%s") do i=i+1 end
        if i > n then break end
        if line:sub(i,i) == "#" then
            comment = line:sub(i)
            break
        end
        local start = i
        if line:sub(i,i) == '"' then
            i=i+1
            local closed=false
            while i <= n do
                local c=line:sub(i,i)
                if c == "\\" then
                    i=i+2
                elseif c == '"' then
                    i=i+1
                    closed=true
                    break
                else
                    i=i+1
                end
            end
            if not closed then return nil, nil, "unterminated quoted token" end
        else
            while i <= n and not line:sub(i,i):match("%s") do i=i+1 end
        end
        tokens[#tokens+1]=line:sub(start,i-1)
        spans[#spans+1]={first=start,last=i-1}
    end
    return tokens, spans, comment
end

local function me_index(tokens)
    if tokens[1] == "?" or tokens[1] == "!" then return 2 end
    return 1
end

local function render(line)
    if not line.changed then return line.raw end
    local replacements=line.replacements or {}
    table.sort(replacements,function(a,b) return a.first > b.first end)
    local out=line.raw
    for _,r in ipairs(replacements) do
        out=out:sub(1,r.first-1)..r.value..out:sub(r.last+1)
    end
    return out
end

local function replace_token(line,index,value)
    local span=line.spans[index]
    if not span then die("target token is missing") end
    line.tokens[index]=value
    line.replacements=line.replacements or {}
    line.replacements[#line.replacements+1]={first=span.first,last=span.last,value=value}
    line.changed=true
end

local function load_file(path)
    local f,err=io.open(path,"rb")
    if not f then die(err or "cannot open input") end
    local lines={}
    for line in f:lines() do
        local t,spans,c,e=tokenize(line)
        if e then f:close(); die(e) end
        lines[#lines+1]={raw=line,tokens=t,spans=spans,comment=c,changed=false,replacements={}}
    end
    f:close()
    return lines
end

local function atomic_write(path, lines)
    local tmp=path..".8311."..tostring(os.time()).."."..tostring(math.random(100000,999999))
    local f,err=io.open(tmp,"wb")
    if not f then die(err or "cannot create temporary file") end
    for _,l in ipairs(lines) do
        f:write(render(l), "\n")
    end
    if not f:close() then os.remove(tmp); die("temporary file close failed") end
    local ok,rename_err=os.rename(tmp,path)
    if not ok then os.remove(tmp); die(rename_err or "atomic rename failed") end
end

local function quoted(value)
    if value:find('[%z\1-\31\127]') then die("control characters are not allowed") end
    if value:find('[\\"]') then die('double quote and backslash are not supported in MIB string fields') end
    return '"'..value..'"'
end

local function set_field(path, me, param, value)
    param=tonumber(param)
    if not param or param < 0 or param > 128 then die("invalid field index") end
    if not tostring(me):match("^%d+$") then die("invalid ME class") end
    local lines=load_file(path)
    local matched=0
    local q=quoted(value)
    for _,l in ipairs(lines) do
        local t=l.tokens
        if #t > 0 then
            local mi=me_index(t)
            if t[mi] == tostring(me) then
                local target=mi+param+1
                if not t[target] then die("target field missing in ME "..me) end
                replace_token(l,target,q)
                matched=matched+1
            end
        end
    end
    if matched == 0 then die("ME class not found: "..me) end
    atomic_write(path,lines)
end

local function set_slot(path, newslot, dry_run)
    newslot=tonumber(newslot)
    if not newslot or newslot < 1 or newslot > 254 or newslot ~= math.floor(newslot) then
        die("slot must be 1..254")
    end

    local lines=load_file(path)

    -- Infer the current slot from priority-queue relationships for UNI 1 only.
    -- Related-port encodings use 0xSS01xxxx, where SS is the slot and 01 is
    -- the UNI number. This avoids mistaking unrelated MEs such as 0x0180 for
    -- another configurable UNI, and it leaves UNI 2+ untouched on multi-UNI MIBs.
    local slot_candidates={}
    for _,l in ipairs(lines) do
        local t=l.tokens
        if #t > 0 then
            local mi=me_index(t)
            if t[mi] == "277" then
                local qinst=(t[mi+1] or ""):lower()
                local port=(t[mi+7] or ""):lower()
                local s,u=port:match("^0x(%x%x)(%x%x)%x%x%x%x$")
                local slot=s and tonumber(s,16) or nil
                if qinst:match("^0x00%x%x$") and slot and slot >= 1 and slot <= 254 and u == "01" then
                    slot_candidates[slot]=true
                end
            end
        end
    end

    local oldslot
    local nslots=0
    for slot in pairs(slot_candidates) do
        nslots=nslots+1
        oldslot=slot
    end
    if nslots == 0 then
        die("cannot infer current UNI-1 slot from priority queue relationships")
    elseif nslots > 1 then
        die("ambiguous UNI-1 slot in priority queue relationships")
    end

    -- A slot is shared by every physical UNI in the related-port encoding.
    -- The historical sed implementation moved all of them, but the static MIB
    -- does not always contain enough ME 5/6 instances to update every UNI
    -- consistently (notably 2U/2U-VoIP profiles). Refuse a non-noop migration
    -- whenever another UNI is present rather than producing a mixed-slot MIB.
    local other_unis={}
    for _,l in ipairs(lines) do
        local t=l.tokens
        if #t > 0 then
            local mi=me_index(t)
            if t[mi] == "277" then
                local qinst=(t[mi+1] or ""):lower()
                local port=(t[mi+7] or ""):lower()
                local ss,uu=port:match("^0x(%x%x)(%x%x)%x%x%x%x$")
                local slot=ss and tonumber(ss,16) or nil
                if qinst:match("^0x00%x%x$") and slot == oldslot and uu and uu ~= "00" and uu ~= "01" then
                    other_unis[uu]=true
                end
            end
        end
    end

    local oldhex=string.format("%02x",oldslot)
    local newhex=string.format("%02x",newslot)
    local source_uni="0x01"..oldhex
    local target_uni="0x01"..newhex

    local counts={}
    for _,l in ipairs(lines) do
        local t=l.tokens
        if #t > 0 then
            local mi=me_index(t)
            local cls=t[mi]
            local inst=t[mi+1]
            if cls and inst then
                local k=cls.."|"..inst:lower()
                counts[k]=(counts[k] or 0)+1
            end
        end
    end

    if (counts["5|"..source_uni] or 0) ~= 1 or (counts["6|"..source_uni] or 0) ~= 1 then
        die("UNI-1 slot does not have exactly one matching ME 5 and ME 6 instance")
    end
    if oldslot == newslot then return end
    if next(other_unis) then
        local ids={}
        for u in pairs(other_unis) do ids[#ids+1]=u end
        table.sort(ids)
        die("slot migration is ambiguous on multi-UNI profile (additional UNI IDs: "..table.concat(ids,",")..")")
    end
    if (counts["5|"..target_uni] or 0) > 0 or (counts["6|"..target_uni] or 0) > 0 then
        die("slot change would collide with an existing Ethernet UNI")
    end

    local changes={}
    local function plan(line,index,newvalue,kind)
        changes[#changes+1]={line=line,index=index,newvalue=newvalue,kind=kind}
    end

    local queue_changes=0
    local instance_changes=0
    for _,l in ipairs(lines) do
        local t=l.tokens
        if #t > 0 then
            local mi=me_index(t)
            local cls=t[mi]
            local inst=t[mi+1]

            if cls == "277" then
                local qinst=(inst or ""):lower()
                local port=(t[mi+7] or ""):lower()
                local s,u,tail=port:match("^0x(%x%x)(%x%x)(%x%x%x%x)$")
                if qinst:match("^0x00%x%x$") and s and u == "01" and tonumber(s,16) == oldslot then
                    plan(l,mi+7,"0x"..newhex..u..tail,"queue-related-port")
                    queue_changes=queue_changes+1
                end
            end

            if cls and inst then
                local target_old,target_new
                if cls == "5" or cls == "6" then
                    target_old=source_uni
                    target_new=target_uni
                else
                    target_old="0x"..oldhex.."01"
                    target_new="0x"..newhex.."01"
                end
                if inst:lower() == target_old then
                    if (counts[cls.."|"..target_old] or 0) > 1 then
                        die("ambiguous duplicate source ME "..cls.." "..target_old)
                    end
                    if target_new ~= target_old and (counts[cls.."|"..target_new] or 0) > 0 then
                        die("slot change would collide with existing ME "..cls.." "..target_new)
                    end
                    plan(l,mi+1,target_new,"instance")
                    instance_changes=instance_changes+1
                end
            end
        end
    end

    if queue_changes == 0 then die("no UNI-1 priority queue relationships were updated") end
    if instance_changes < 2 then die("incomplete slot-linked ME set") end
    if dry_run then return end

    for _,c in ipairs(changes) do
        replace_token(c.line,c.index,c.newvalue)
    end
    atomic_write(path,lines)
end

math.randomseed(os.time())
local cmd=arg[1]
if cmd=="set-field" then
    if #arg ~= 5 then die("usage: set-field <file> <class> <field-index> <value>") end
    set_field(arg[2],arg[3],arg[4],arg[5])
elseif cmd=="set-slot" then
    if #arg ~= 3 then die("usage: set-slot <file> <slot>") end
    set_slot(arg[2],arg[3],false)
elseif cmd=="check-slot" then
    if #arg ~= 3 then die("usage: check-slot <file> <slot>") end
    set_slot(arg[2],arg[3],true)
else
    die("unknown command")
end
