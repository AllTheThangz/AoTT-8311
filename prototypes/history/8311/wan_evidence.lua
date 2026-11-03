-- H-017 source-only router-probe evidence and timeline model.
-- Does not perform, schedule or authenticate probes; no shell/network/filesystem.
-- An authorized router-side adapter must verify provenance independently.
local M = {}

local ALLOWED={dns=true,https=true,tcp=true,icmp=true}
local MAX_PROBES=4
local MAX_GAP=3600
local MAX_QUERY=100
local function int(v,a,b)
    return type(v)=="number" and v==v and v~=math.huge and
           v~=-math.huge and v==math.floor(v) and v>=a and v<=b
end
local function time(v)
    return type(v)=="number" and v==v and v~=math.huge and
           v~=-math.huge and v>=0 and v<=1e12
end
local function token(v)
    return type(v)=="string" and #v>=1 and #v<=80 and
           v:match("^[%w_.%-]+$")~=nil
end
local function clone(record)
    local out={}
    for k,v in pairs(record) do
        if type(v)=="number" or type(v)=="string" or type(v)=="boolean" then
            out[k]=v
        end
    end
    return out
end

local function cap(value,default,upper)
    if value==nil then return default end
    if not int(value,2,upper) then return nil end
    return value
end

function M.new(options)
    if options~=nil and type(options)~="table" then
        return nil,"invalid_options"
    end
    options=options or {}
    local max_events=cap(options.max_events,64,256)
    local max_samples=cap(options.max_samples,120,720)
    if not max_events or not max_samples then
        return nil,"invalid_capacity"
    end
    return {
        schema=1,
        max_events=max_events,max_samples=max_samples,
        events={},events_head=1,events_count=0,
        samples={},samples_head=1,samples_count=0,
        last=nil,accepted=0,
    }
end

-- O(1) fixed-capacity ring insertion.
local function put(state,which,value)
    local records=state[which]
    local count=state[which.."_count"]
    local head=state[which.."_head"]
    local size=state["max_"..which]
    if count<size then
        records[((head+count-1)%size)+1]=value
        state[which.."_count"]=count+1
    else
        records[head]=value
        state[which.."_head"]=(head%size)+1
    end
end

-- This parser accepts only a numeric target slot, known protocol/result,
-- and optional bounded latency. It ignores labels, IPs, URLs and credentials.
local function inspect(raw)
    if type(raw)~="table" or raw.origin~="router_wan" or
       raw.clock_domain~="router_monotonic" or not token(raw.boot) or
       not time(raw.uptime) or type(raw.probes)~="table" then
        return nil,"invalid_router_probe_record"
    end
    local count=0
    for k in pairs(raw.probes) do
        if not int(k,1,MAX_PROBES) then
            return nil,"invalid_probe_index"
        end
        count=count+1
    end
    if count>MAX_PROBES or #raw.probes~=count then
        return nil,"invalid_probe_count"
    end
    local passed,failed,unknown=0,0,0
    local fastest,slowest=nil,nil
    local slots={}
    for _,probe in ipairs(raw.probes) do
        if type(probe)~="table" or not int(probe.slot,1,MAX_PROBES)
           or slots[probe.slot] or not ALLOWED[probe.kind] or
           (probe.result~="pass" and probe.result~="fail" and
            probe.result~="unknown") then
            return nil,"invalid_probe"
        end
        if probe.latency_ms~=nil and
           (probe.result~="pass" or not int(probe.latency_ms,0,120000)) then
            return nil,"invalid_probe_latency"
        end
        slots[probe.slot]=true
        if probe.result=="pass" then
            passed=passed+1
            if probe.latency_ms~=nil then
                fastest=fastest and math.min(fastest,probe.latency_ms)
                    or probe.latency_ms
                slowest=slowest and math.max(slowest,probe.latency_ms)
                    or probe.latency_ms
            end
        elseif probe.result=="fail" then failed=failed+1
        else unknown=unknown+1 end
    end
    local status
    if count==0 then status="unavailable"
    elseif passed>0 then status="one_or_more_targets_reached"
    elseif failed==count then status="all_submitted_probes_failed"
    else status="inconclusive" end
    return {
        boot=raw.boot,uptime=raw.uptime,status=status,
        passed=passed,failed=failed,unknown=unknown,count=count,
        latency_ms_min=fastest,latency_ms_max=slowest,
    }
end

local function event(state,kind,when,details)
    local value={
        kind=kind,
        at_router_uptime=when,
        walltime_trust="unknown",
        isp_failure_cause_unverified=true,
    }
    if details then
        for k,v in pairs(details) do value[k]=v end
    end
    put(state,"events",value)
end

function M.ingest(state,raw)
    if type(state)~="table" or state.schema~=1 or
       type(state.events)~="table" or type(state.samples)~="table" or
       not int(state.max_events,2,256) or
       not int(state.max_samples,2,720) then
        return nil,"invalid_state"
    end
    local current,reason=inspect(raw)
    if not current then return nil,reason end
    local last=state.last
    if last and last.boot==current.boot and current.uptime<=last.uptime then
        return nil,"nonmonotonic_router_time"
    end
    local new_events=0
    local function add(kind,details)
        event(state,kind,current.uptime,details)
        new_events=new_events+1
    end
    if last then
        if last.boot~=current.boot then
            add("router_reboot_observed")
        else
            local elapsed=current.uptime-last.uptime
            if elapsed>MAX_GAP then
                add("router_probe_sampling_gap",{
                    observation_window_seconds=elapsed,
                })
            elseif last.status~=current.status then
                -- Failed reachability probes are not proof the ISP failed.
                -- A transition through unavailable/inconclusive is evidence
                -- changing, not an externally verified outage/recovery.
                local decisive={
                    one_or_more_targets_reached=true,
                    all_submitted_probes_failed=true,
                }
                local kind=(decisive[last.status] and decisive[current.status])
                    and "router_probe_result_change"
                    or "router_probe_evidence_change"
                add(kind,{
                    from=last.status,to=current.status,
                    observation_window_seconds=elapsed,
                })
            end
        end
    end

    put(state,"samples",{
        at_router_uptime=current.uptime,
        status=current.status,
        passed=current.passed,failed=current.failed,
        unknown=current.unknown,total=current.count,
        latency_ms_min=current.latency_ms_min,
        latency_ms_max=current.latency_ms_max,
        walltime_trust="unknown",
    })
    -- Only internal state retains boot ID. No target URLs/IPs ever stored.
    state.last={
        boot=current.boot,uptime=current.uptime,status=current.status,
    }
    state.accepted=state.accepted+1
    return {
        schema=1,
        status=current.status,
        passed=current.passed,failed=current.failed,
        unknown=current.unknown,total=current.count,
        latency_ms_min=current.latency_ms_min,
        latency_ms_max=current.latency_ms_max,
        events_added=new_events,
        samples_retained=state.samples_count,
        events_retained=state.events_count,
        source="declared_router_wan_probes",
        declared_source_is_not_authenticated=true,
        no_isp_failure_cause_proven=true,
        not_global_internet_reachability_proof=true,
        no_network_or_device_action=true,
    }
end

function M.recent(state,which,limit)
    if type(state)~="table" or state.schema~=1 then
        return nil,"invalid_state"
    end
    if which~="events" and which~="samples" then
        return nil,"unknown_history_collection"
    end
    limit=limit or 24
    if not int(limit,1,MAX_QUERY) then
        return nil,"invalid_query_limit"
    end
    local buffer=state[which]
    local max=state["max_"..which]
    local count=state[which.."_count"]
    local head=state[which.."_head"]
    if type(buffer)~="table" or not int(max,2,720) or
       not int(count,0,max) or not int(head,1,max) then
        return nil,"corrupt_history_state"
    end
    local out={}
    for offset=math.max(0,count-limit),count-1 do
        local index=((head+offset-1)%max)+1
        if type(buffer[index])~="table" then
            return nil,"corrupt_history_state"
        end
        out[#out+1]=clone(buffer[index])
    end
    return out
end

-- Keep the three evidence layers separate. Neither a PON association nor
-- a nonzero host speed alone is WAN reachability or subscriber throughput.
-- The router result remains a *reported* probe until its source adapter
-- is independently authenticated and hardware-qualified.
function M.combine(pon_state,host_speed_mbps,router_receipt)
    local pon="unknown"
    if int(pon_state,0,255) then
        pon=pon_state==51 and "o5_1_associated" or "not_o5_1_associated"
    end
    local host="unknown"
    if int(host_speed_mbps,0,100000) then
        host=host_speed_mbps>0 and "host_speed_nonzero" or "host_speed_zero"
    end
    local wan="unavailable"
    if type(router_receipt)=="table" and router_receipt.schema==1 and
       router_receipt.source=="declared_router_wan_probes" and
       router_receipt.no_isp_failure_cause_proven==true and
       router_receipt.declared_source_is_not_authenticated==true then
        local known={
            unavailable=true,inconclusive=true,
            one_or_more_targets_reached=true,
            all_submitted_probes_failed=true,
        }
        if known[router_receipt.status] then wan=router_receipt.status end
    end
    return {
        schema=1,
        pon_association=pon,
        host_link_speed=host,
        router_probe_evidence=wan,
        simultaneous_measurement_unverified=true,
        router_source_authenticated=false,
        customer_wan_bandwidth_unmeasured=true,
        proves_isp_fault=false,
        proves_full_internet_reachability=false,
        no_device_write=true,
    }
end

return M
