-- H-018 synthetic UI data from the real Lua preferences catalogue.
-- Emits test-only JSON. No ONU, running collector or storage access.
local source=assert(arg[1],"Source-only preferences module required")
local model=assert(loadfile(source))()
local function quoted(text)
    return '"'..text:gsub('[%z\1-\31\\\"<>&]',function(c)
        if c=='\\' then return '\\\\' end
        if c=='"' then return '\\"' end
        return string.format("\\u%04x",c:byte())
    end)..'"'
end
local function json(value)
    local t=type(value)
    if t=="string" then return quoted(value) end
    if t=="boolean" then return value and "true" or "false" end
    if t=="number" then
        assert(value==value and value~=math.huge and value~=-math.huge)
        return string.format("%.15g",value)
    end
    assert(t=="table","Non-json fixture value")
    local n=#value
    local array=n>0
    if array then
        for k in pairs(value) do
            if type(k)~="number" or k<1 or k>n or k~=math.floor(k) then
                array=false
                break
            end
        end
    end
    local out={}
    if array then
        for i=1,n do out[#out+1]=json(value[i]) end
        return "["..table.concat(out,",").."]"
    end
    local keys={}
    for k in pairs(value) do
        assert(type(k)=="string")
        keys[#keys+1]=k
    end
    table.sort(keys)
    for _,k in ipairs(keys) do
        out[#out+1]=quoted(k)..":"..json(value[k])
    end
    return "{"..table.concat(out,",").."}"
end
local profile=model.source_profile()
local state=model.defaults()
local catalogue=assert(model.describe(profile))
local example=assert(model.preview(state,{
    pon_interval_seconds=120,ram_sample_limit=360,
},1,profile))
local denied,denial=model.preview(state,{
    pon_interval_seconds=30,host_interval_seconds=30,
},1,profile)
assert(denied==nil and denial=="probe_budget_exceeds_residential_limit")
local payload={
    schema=1,state=state,catalogue=catalogue,
    demo=true,output_is_live=false,
    real_save_available=false,alerts_running=false,
    firmware_persistence_available=false,
    source_reference={
        changed_fields=example.changed_fields,
        worst_case_command_seconds_per_hour=
            example.metrics.worst_case_command_seconds_per_hour,
        pon_calls_per_hour=example.metrics.pon_calls_per_hour,
        host_calls_per_hour=example.metrics.host_calls_per_hour,
        ram_sample_limit=example.values.ram_sample_limit,
        rejected_high_duty_reason=denial,
    },
}
print("AOTT_H018_SETTINGS_FIXTURE="..json(payload))
