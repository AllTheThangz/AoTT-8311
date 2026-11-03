-- AoTT-8311 H-015 source-only bounded persistent history journal model.
-- No filesystem, flash, shell, timer, network, LuCI or startup entrypoint.
-- Future storage adapter MUST enforce file+parent-directory fsync, atomic
-- replacement, fixed paths, ownership and locking. Not yet hardware qualified.
local M={}
local MAX_SLOT_BYTES=160*1024
local MAX_EVENTS=256
local MAX_HOURS=2160
local MAX_RECORDS=MAX_EVENTS+MAX_HOURS
local MIN_FLUSH_MS=900000
local MAX_GENERATION=9007199254740990
local MAX_EPOCH=1000000
local MAX_UPTIME_MS=1000000000000
local MAX_WALL=4102444800
local MIN_WALL=946684800
local EVENT_TO_CODE={
    pon_state_change="P",host_link_change="L",
    reboot_observed="R",source_changed="C",
    sampling_gap="G",observation_unavailable="U",
}
local CODE_TO_EVENT={}
for name,code in pairs(EVENT_TO_CODE) do CODE_TO_EVENT[code]=name end
local CHANNEL_CODES={[""]=0,pon=1,host=2,["pon,host"]=3}
local CODE_CHANNELS={[0]="",[1]="pon",[2]="host",[3]="pon,host"}

local function int(v,a,b)
    return type(v)=="number" and v==v and v~=math.huge and
           v~=-math.huge and math.floor(v)==v and v>=a and v<=b
end
local function finite(v,a,b)
    return type(v)=="number" and v==v and v~=math.huge and
           v~=-math.huge and v>=a and v<=b
end
local function decimal(v)
    return string.format("%.0f",v)
end
local function uint(text,lo,hi)
    if type(text)~="string" or not text:match("^%d+$") or
       (#text>1 and text:sub(1,1)=="0") or #text>16 then return nil end
    local value=tonumber(text)
    if int(value,lo,hi) and decimal(value)==text then return value end
end
local function signed(text,hi)
    if text=="-1" then return -1 end
    return uint(text,0,hi)
end
local function ms(v,max)
    if not finite(v,0,max/1000) then return nil end
    local result=math.floor(v*1000+0.5)
    if int(result,0,max) then return result end
end
local function to_milli(v)
    if v==nil then return -1 end
    if not finite(v,0,100000) then return nil end
    return math.floor(v*1000+0.5)
end
local function wall(record)
    if record.walltime_trust~="verified" then return 0 end
    if not int(record.walltime_unix,MIN_WALL,MAX_WALL) then return nil end
    return record.walltime_unix
end
local function normalize(record)
    if type(record)~="table" or
       not int(record.epoch_index,1,MAX_EPOCH) then
        return nil,"invalid_record_epoch"
    end
    local uptime=ms(record.at_uptime,MAX_UPTIME_MS)
    local timestamp=wall(record)
    if not uptime or not timestamp then return nil,"invalid_record_time" end
    if record.type=="event" then
        local code=EVENT_TO_CODE[record.event_kind]
        if not code then return nil,"invalid_event_type" end
        local from=record.from==nil and -1 or record.from
        local to=record.to==nil and -1 or record.to
        if not int(from,-1,100000) or not int(to,-1,100000) then
            return nil,"invalid_event_value"
        end
        local duration=record.observation_window_seconds==nil and 0 or
            ms(record.observation_window_seconds,MAX_UPTIME_MS)
        if not duration then return nil,"invalid_event_window" end
        local channel=CHANNEL_CODES[record.channels or ""]
        if channel==nil then return nil,"invalid_event_channels" end
        return {
            type="event",epoch_index=record.epoch_index,
            uptime_ms=uptime,wall=timestamp,code=code,
            from=from,to=to,window_ms=duration,channel=channel,
        }
    elseif record.type=="hourly_summary" then
        if record.rate_source~="host_ethernet_byte_counters" then
            return nil,"unqualified_summary_source"
        end
        local rx=to_milli(record.rx_average_mbps)
        local tx=to_milli(record.tx_average_mbps)
        local rx_cover=ms(record.rx_covered_seconds,3600000)
        local tx_cover=ms(record.tx_covered_seconds,3600000)
        if rx==nil or tx==nil or rx_cover==nil or tx_cover==nil or
           not int(record.sample_count,0,720) or
           (rx==-1 and rx_cover>0) or (tx==-1 and tx_cover>0) or
           (rx>=0 and rx_cover==0) or (tx>=0 and tx_cover==0) then
            return nil,"invalid_hourly_summary"
        end
        return {
            type="hourly_summary",epoch_index=record.epoch_index,
            uptime_ms=uptime,wall=timestamp,
            rx=rx,tx=tx,rx_covered_ms=rx_cover,tx_covered_ms=tx_cover,
            sample_count=record.sample_count,
        }
    end
    return nil,"unsupported_history_record"
end

local function encode_row(record)
    if record.type=="event" then
        return table.concat({
            "E",decimal(record.epoch_index),decimal(record.uptime_ms),
            decimal(record.wall),record.code,decimal(record.from),
            decimal(record.to),decimal(record.window_ms),
            decimal(record.channel)
        },"|")
    end
    return table.concat({
        "S",decimal(record.epoch_index),decimal(record.uptime_ms),
        decimal(record.wall),decimal(record.rx),decimal(record.tx),
        decimal(record.rx_covered_ms),decimal(record.tx_covered_ms),
        decimal(record.sample_count),
    },"|")
end
local function split(line)
    local fields={}
    for value in (line.."|"):gmatch("(.-)|") do
        fields[#fields+1]=value
        if #fields>10 then return nil end
    end
    return fields
end
local function parse_row(line)
    if type(line)~="string" or #line>120 then return nil end
    local f=split(line)
    if not f or #f~=9 then return nil end
    local epoch=uint(f[2],1,MAX_EPOCH)
    local up=uint(f[3],0,MAX_UPTIME_MS)
    local clock=uint(f[4],0,MAX_WALL)
    if not epoch or not up or not clock or
       (clock~=0 and clock<MIN_WALL) then return nil end
    local input={
        epoch_index=epoch,at_uptime=up/1000,
        walltime_trust=clock>0 and "verified" or "unknown",
        walltime_unix=clock>0 and clock or nil,
    }
    if f[1]=="E" then
        local from=signed(f[6],100000)
        local to=signed(f[7],100000)
        local duration=uint(f[8],0,MAX_UPTIME_MS)
        local channel=uint(f[9],0,3)
        if not CODE_TO_EVENT[f[5]] or not from or not to or
           not duration or not channel then return nil end
        input.type="event"
        input.event_kind=CODE_TO_EVENT[f[5]]
        input.from=from<0 and nil or from
        input.to=to<0 and nil or to
        input.observation_window_seconds=duration/1000
        input.channels=CODE_CHANNELS[channel]
    elseif f[1]=="S" then
        local rx=signed(f[5],100000000)
        local tx=signed(f[6],100000000)
        local rx_cov=uint(f[7],0,3600000)
        local tx_cov=uint(f[8],0,3600000)
        local count=uint(f[9],0,720)
        if not rx or not tx or not rx_cov or not tx_cov or
           not count then return nil end
        input.type="hourly_summary"
        input.rate_source="host_ethernet_byte_counters"
        input.rx_average_mbps=rx<0 and nil or rx/1000
        input.tx_average_mbps=tx<0 and nil or tx/1000
        input.rx_covered_seconds=rx_cov/1000
        input.tx_covered_seconds=tx_cov/1000
        input.sample_count=count
    else
        return nil
    end
    local row=normalize(input)
    if row and encode_row(row)==line then return row end
end

-- Adler-32 detects accidental truncation/corruption. It is NOT a MAC or
-- security signature against malicious local writes.
local function checksum(data)
    local a,b=1,0
    for i=1,#data do
        a=(a+data:byte(i))%65521
        b=(b+a)%65521
    end
    return string.format("%04x%04x",b,a)
end
local function copy(records)
    local result={}
    for _,value in ipairs(records) do
        local row={}
        for k,v in pairs(value) do row[k]=v end
        result[#result+1]=row
    end
    return result
end
local function order(records)
    local event_count,hour_count=0,0
    local last
    for _,row in ipairs(records) do
        if type(row)~="table" then return nil,"bad_history_record" end
        if row.type=="event" then event_count=event_count+1
        elseif row.type=="hourly_summary" then hour_count=hour_count+1
        else return nil,"invalid_record_type" end
        if event_count>MAX_EVENTS or hour_count>MAX_HOURS then
            return nil,"history_capacity_exceeded"
        end
        if last and (row.epoch_index<last.epoch_index or
           (row.epoch_index==last.epoch_index and
            row.uptime_ms<last.uptime_ms)) then
            return nil,"history_time_regressed"
        end
        last=row
    end
    return true
end
function M.pack(records,generation,write_epoch,write_uptime_ms)
    if type(records)~="table" or #records>MAX_RECORDS or
       not int(generation,1,MAX_GENERATION) or
       not int(write_epoch,1,MAX_EPOCH) or
       not int(write_uptime_ms,MIN_FLUSH_MS,MAX_UPTIME_MS) then
        return nil,"invalid_journal_header"
    end
    -- The staging input may be a caller-owned Lua table. Revalidate every
    -- normalized row before formatting a would-be durable image.
    for _,record in ipairs(records) do
        if type(record)~="table" then return nil,"invalid_staged_record" end
        local ok,line=pcall(encode_row,record)
        if not ok or type(line)~="string" or not parse_row(line) then
            return nil,"invalid_staged_record"
        end
    end
    local ok,why=order(records)
    if not ok then return nil,why end
    if records[#records] and
       (records[#records].epoch_index>write_epoch or
        (records[#records].epoch_index==write_epoch and
         records[#records].uptime_ms>write_uptime_ms)) then
        return nil,"journal_writer_before_records"
    end
    local lines={"AOTT15|1|"..decimal(generation).."|"..
        decimal(write_epoch).."|"..decimal(write_uptime_ms)..
        "|" ..decimal(#records)}
    for _,row in ipairs(records) do lines[#lines+1]=encode_row(row) end
    local data=table.concat(lines,"\n").."\n"
    local image=data.."checksum="..checksum(data).."\n"
    if #image>MAX_SLOT_BYTES then return nil,"journal_slot_full" end
    return image
end
function M.unpack(image)
    if type(image)~="string" or #image<35 or #image>MAX_SLOT_BYTES or
       image:find("[%z\1-\8\11\12\14-\31\127]") then
        return nil,"invalid_journal_bytes"
    end
    local content,hash=image:match("^(.*\n)checksum=(%x%x%x%x%x%x%x%x)\n$")
    if not content or hash~=checksum(content) then
        return nil,"journal_integrity_failed"
    end
    local lines={}
    for line in content:gmatch("([^\n]*)\n") do
        if #line==0 or #line>120 then return nil,"invalid_journal_line" end
        lines[#lines+1]=line
        if #lines>MAX_RECORDS+1 then return nil,"journal_record_limit" end
    end
    local header=split(lines[1] or "")
    if not header or #header~=6 or header[1]~="AOTT15" or
       header[2]~="1" then return nil,"unsupported_journal_version" end
    local seq=uint(header[3],1,MAX_GENERATION)
    local write_epoch=uint(header[4],1,MAX_EPOCH)
    local write_ms=uint(header[5],MIN_FLUSH_MS,MAX_UPTIME_MS)
    local count=uint(header[6],0,MAX_RECORDS)
    if not seq or not write_epoch or not write_ms or
       not count or count~=#lines-1 then
        return nil,"invalid_journal_header"
    end
    local records={}
    for i=2,#lines do
        local record=parse_row(lines[i])
        if not record then return nil,"invalid_history_record" end
        records[#records+1]=record
    end
    local ok,why=order(records)
    if not ok then return nil,why end
    if records[#records] and
       (records[#records].epoch_index>write_epoch or
        (records[#records].epoch_index==write_epoch and
         records[#records].uptime_ms>write_ms)) then
        return nil,"writer_behind_history"
    end
    -- Canonical re-encode detects any exotic alternate textual encoding.
    local encoded=M.pack(records,seq,write_epoch,write_ms)
    if encoded~=image then return nil,"noncanonical_journal" end
    return {
        sequence=seq,write_epoch=write_epoch,write_uptime_ms=write_ms,
        records=records,record_count=#records,
    }
end

local function new_state(records,sequence,active,write_epoch,write_uptime_ms)
    return {
        schema=1,records=copy(records),sequence=sequence,
        active=active,write_epoch=write_epoch,
        write_uptime_ms=write_uptime_ms,
        dirty=false,uncertain=false,evicted=0,
    }
end
local function adapter_ok(adapter)
    return type(adapter)=="table" and
        type(adapter.read_slot)=="function" and
        type(adapter.replace_slot)=="function"
end
function M.recover(adapter)
    if not adapter_ok(adapter) then return nil,"invalid_store_adapter" end
    local valid,raw,missing={}, {},0
    for _,slot in ipairs({"A","B"}) do
        local ok,value,reason=pcall(adapter.read_slot,slot)
        if not ok then return nil,"journal_storage_unavailable" end
        if value==nil then
            if reason~="missing" then
                return nil,"journal_storage_unavailable"
            end
            missing=missing+1
        elseif type(value)~="string" or #value>MAX_SLOT_BYTES then
            raw[slot]="invalid"
        else
            local record=M.unpack(value)
            if record then valid[slot]=record;raw[slot]=value
            else raw[slot]="invalid" end
        end
    end
    if missing==2 then
        return new_state({},0,nil,nil,nil),{
            state="empty",recovered=false,
        }
    end
    local a,b=valid.A,valid.B
    if not a and not b then return nil,"no_valid_history_checkpoint" end
    if a and b and a.sequence==b.sequence and raw.A~=raw.B then
        return nil,"ambiguous_history_generation"
    end
    local selected=(a and (not b or a.sequence>=b.sequence)) and "A" or "B"
    local found=valid[selected]
    return new_state(found.records,found.sequence,selected,
                     found.write_epoch,found.write_uptime_ms),{
        state=(a and b) and "two_valid_checkpoints" or "recovered_single_slot",
        recovered=true,sequence=found.sequence,active_slot=selected,
        records=#found.records,other_slot_valid=a~=nil and b~=nil,
    }
end

local function count_type(records,type_name)
    local n=0
    for _,record in ipairs(records) do
        if record.type==type_name then n=n+1 end
    end
    return n
end
function M.append(state,input)
    if type(state)~="table" or state.schema~=1 or
       type(state.records)~="table" or state.uncertain then
        return nil,"unsafe_history_state"
    end
    local row,why=normalize(input)
    if not row then return nil,why end
    local last=state.records[#state.records]
    if last and (row.epoch_index<last.epoch_index or
       (row.epoch_index==last.epoch_index and
        row.uptime_ms<last.uptime_ms)) then
        return nil,"nonmonotonic_history_record"
    end
    state.records[#state.records+1]=row
    local type_limit=row.type=="event" and MAX_EVENTS or MAX_HOURS
    local of_type=count_type(state.records,row.type)
    if of_type>type_limit then
        for index,old in ipairs(state.records) do
            if old.type==row.type then
                table.remove(state.records,index)
                state.evicted=state.evicted+1
                break
            end
        end
    end
    state.dirty=true
    return {
        accepted=true,records=#state.records,
        evicted=state.evicted,private_only=true,
        no_flash_write=true,
    }
end

-- The caller must supply its OWN current boot-epoch from the recovered
-- sequence contract. The processor never infers it from wall-clock time.
-- A new boot must survive 15 minutes of uptime before a routine write.
function M.flush(state,adapter,current_epoch,now_uptime)
    if not adapter_ok(adapter) then return nil,"invalid_store_adapter" end
    if type(state)~="table" or state.schema~=1 or state.uncertain then
        return nil,"unsafe_history_state"
    end
    if not state.dirty then return nil,"no_uncommitted_history" end
    if not int(current_epoch,1,MAX_EPOCH) then
        return nil,"invalid_writer_epoch"
    end
    local now_ms=ms(now_uptime,MAX_UPTIME_MS)
    if not now_ms then return nil,"invalid_writer_uptime" end
    local latest=state.records[#state.records]
    if latest and (current_epoch<latest.epoch_index or
       (current_epoch==latest.epoch_index and
        now_ms<latest.uptime_ms)) then
        return nil,"writer_before_newest_record"
    end
    if state.write_epoch and current_epoch<state.write_epoch then
        return nil,"writer_epoch_regressed"
    end
    if now_ms<MIN_FLUSH_MS or
       (state.write_epoch==current_epoch and
        now_ms-state.write_uptime_ms<MIN_FLUSH_MS) then
        return nil,"routine_write_deferred"
    end
    if state.sequence>=MAX_GENERATION then
        return nil,"journal_generation_exhausted"
    end
    local rows=copy(state.records)
    local discarded=0
    local image,reason=M.pack(rows,state.sequence+1,current_epoch,now_ms)
    while not image and reason=="journal_slot_full" and #rows>0 do
        table.remove(rows,1)
        discarded=discarded+1
        image,reason=M.pack(rows,state.sequence+1,current_epoch,now_ms)
    end
    if not image then return nil,reason or "checkpoint_unavailable" end
    local nextslot=state.active=="A" and "B" or "A"
    -- Each adapter replace MUST write a *different* slot using a temp file
    -- and verify atomic rename durability. No storage adapter ships here.
    local ok,written=pcall(adapter.replace_slot,nextslot,image)
    if not ok or written~=true then
        state.uncertain=true
        return nil,"checkpoint_write_unverified"
    end
    local read_ok,readback=pcall(adapter.read_slot,nextslot)
    if not read_ok or readback~=image then
        state.uncertain=true
        return nil,"checkpoint_readback_unverified"
    end
    local verified=M.unpack(readback)
    if not verified or verified.sequence~=state.sequence+1 then
        state.uncertain=true
        return nil,"checkpoint_integrity_unverified"
    end
    state.records=rows
    state.sequence=verified.sequence
    state.active=nextslot
    state.write_epoch=current_epoch
    state.write_uptime_ms=now_ms
    state.evicted=state.evicted+discarded
    state.dirty=false
    return {
        status="offline_adapter_checkpoint_verified",
        active_slot=nextslot,sequence=state.sequence,
        records=#rows,evicted_on_size_limit=discarded,
        elapsed_cadence_at_least_15_minutes=true,
        verified_atomic_filesystem_semantics=false,
        source_only_not_deployed=true,
        hardware_flash_wear_unverified=true,
        no_isp_outage_or_time_continuity_proof=true,
    }
end

function M.inspect(state,limit)
    if type(state)~="table" or state.schema~=1 or
       type(state.records)~="table" or state.uncertain then
        return nil,"unsafe_history_state"
    end
    limit=limit or 50
    if not int(limit,1,100) then return nil,"invalid_export_limit" end
    local items={}
    for index=math.max(1,#state.records-limit+1),#state.records do
        local row=state.records[index]
        local entry={
            type=row.type,epoch_index=row.epoch_index,
            at_uptime=row.uptime_ms/1000,
            walltime_trust=row.wall==0 and "unknown" or "verified",
        }
        if row.wall~=0 then entry.walltime_unix=row.wall end
        if row.type=="event" then
            entry.event_kind=CODE_TO_EVENT[row.code]
            if row.from>=0 then entry.from=row.from end
            if row.to>=0 then entry.to=row.to end
            if row.window_ms>0 then
                entry.observation_window_seconds=row.window_ms/1000
            end
            if row.channel>0 then
                entry.channels=CODE_CHANNELS[row.channel]
            end
        else
            if row.rx>=0 then entry.rx_average_mbps=row.rx/1000 end
            if row.tx>=0 then entry.tx_average_mbps=row.tx/1000 end
            entry.rx_covered_seconds=row.rx_covered_ms/1000
            entry.tx_covered_seconds=row.tx_covered_ms/1000
            entry.sample_count=row.sample_count
            entry.source="host_ethernet_byte_counters"
        end
        items[#items+1]=entry
    end
    return {
        schema=1,records=items,records_returned=#items,
        retained_total=#state.records,
        contains_raw_counters=false,contains_device_identity=false,
        cross_boot_walltime_verified=false,
        proved_90_day_retention=false,
        source_only_not_deployed=true,
    }
end

-- A calendar-range count is anchored ONLY to the newest explicitly
-- verified walltime retained in this journal, not the current wall clock.
-- It is not proof of 7/30/90-day continuous retention, since interrupted
-- collection and unknown-clock periods cannot be reconstructed.
function M.calendar_counts(state,days)
    if type(state)~="table" or state.schema~=1 or
       type(state.records)~="table" or state.uncertain then
        return nil,"unsafe_history_state"
    end
    if days~=7 and days~=30 and days~=90 then
        return nil,"unsupported_calendar_range"
    end
    local newest=nil
    local unknown=0
    for _,row in ipairs(state.records) do
        if type(row)~="table" or not int(row.wall,0,MAX_WALL) then
            return nil,"invalid_retained_clock"
        end
        if row.wall==0 then unknown=unknown+1
        else newest=not newest and row.wall or math.max(newest,row.wall) end
    end
    local answer={
        schema=1,requested_days=days,
        anchor_source="latest_explicitly_verified_record_walltime",
        full_period_retention_proven=false,
        continuous_collection_proven=false,
        current_calendar_time_verified=false,
        actual_isp_availability_proven=false,
        unknown_calendar_time_records=unknown,
        hourly_summaries=0,change_events=0,
        source_only_not_deployed=true,
    }
    if not newest then
        answer.status="no_verified_calendar_anchor"
        return answer
    end
    local cutoff=newest-days*86400
    local earliest
    for _,row in ipairs(state.records) do
        if row.wall>=cutoff and row.wall<=newest and row.wall>0 then
            if row.type=="hourly_summary" then
                answer.hourly_summaries=answer.hourly_summaries+1
            elseif row.type=="event" then
                answer.change_events=answer.change_events+1
            else return nil,"invalid_retained_record_type" end
            earliest=earliest and math.min(earliest,row.wall) or row.wall
        end
    end
    answer.status="partial_verified_walltime_evidence"
    answer.latest_verified_walltime_unix=newest
    answer.cutoff_walltime_unix=cutoff
    answer.earliest_matching_walltime_unix=earliest
    answer.observed_span_seconds=earliest and newest-earliest or 0
    return answer
end

M.MAX_SLOT_BYTES=MAX_SLOT_BYTES
M.MAX_LOGICAL_BYTES=3*MAX_SLOT_BYTES
M.MIN_FLUSH_SECONDS=MIN_FLUSH_MS/1000
M.MAX_EVENTS=MAX_EVENTS
M.MAX_HOURLY_SUMMARIES=MAX_HOURS
return M
