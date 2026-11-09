-- C-011: fixed-key read-only OMCI reporting source probe.
-- Never reads PON serial, LOID, registration secrets, real bank selector,
-- root password, full boot environment, or raw firmware image contents.
local M={}
local model=require "8311.effective_reporting_state"

local function bounded(value,max)
    if type(value)~="string" or #value>max+2 then return nil end
    value=value:gsub("[\r\n]+$","")
    if #value>max or value:find("[%z\1-\31\127]") then return nil end
    return value
end
local function safely(fn,...)
    local good,value=pcall(fn,...)
    if good then return value end
end
function M.capture(adapter)
    if type(adapter)~="table" or
       type(adapter.environment)~="function" or
       type(adapter.image_label)~="function" then
        return nil,"invalid_reporting_adapter"
    end
    local saved={}
    for _,id in ipairs(model.fields) do
        saved[id]=bounded(safely(adapter.environment,id),
                          id=="fw_match_b64" and 255 or 32)
    end
    local images={
        A=bounded(safely(adapter.image_label,"A"),14),
        B=bounded(safely(adapter.image_label,"B"),14),
    }
    return model.inspect(saved,images)
end

-- Inherits the existing LuCI authenticated /admin/8311 route.
-- Never supplies a string originating from a browser or a saved setting
-- as a command argument. Environment getters have fixed argument IDs.
function M.live_reporting()
    local ok,record=pcall(function()
        local web=require "8311.webutil"
        local function read_env(key,base,limit,encoded)
            local argv={"/usr/bin/timeout","-k","1","3",
                        "/usr/sbin/fwenv_get"}
            if not base then argv[#argv+1]="--8311" end
            if encoded then argv[#argv+1]="--base64" end
            argv[#argv+1]=key
            local status,output,overflow=web.capture(argv,limit)
            if status==0 and overflow==false and
               type(output)=="string" and #output<=limit then
                return output
            end
        end
        return M.capture({
            environment=function(id)
                if model.field_set[id]~=true then return nil end
                return read_env(id,false,
                    id=="fw_match_b64" and 258 or 36,false)
            end,
            image_label=function(bank)
                if bank~="A" and bank~="B" then return nil end
                return read_env("img_version"..bank,true,32)
            end,
        })
    end)
    if not ok or type(record)~="table" or record.schema~=1 or
       record.no_registration_secret_read~=true or
       record.no_subscriber_identity_exported~=true or
       record.no_raw_environment_value_exported~=true or
       record.source_only_not_hardware_qualified~=true then
        return nil,"reporting_readback_unavailable"
    end
    return record
end
return M
