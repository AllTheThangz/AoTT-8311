-- V3r4 RAM-only host Ethernet error/drop sampling.
-- No device I/O; validates vendor-named counters, reboot/reset and export.
local root=assert(arg[1],"overlay Lua root required")
package.path=root.."/?.lua;"..package.path
local native=require "8311.history_native_probe"
local sampler=require "8311.history_sampler"
local exporter=require "8311.history_export"
local shape=require "8311.history_snapshot_shape"
local checks=0
local function same(actual,expected,why)
    checks=checks+1
    assert(actual==expected,"INTEGRITY_FIXTURE:"..why.." "..tostring(actual)..
           " not "..tostring(expected))
end
local function snapshot(boot,uptime,bytes,counters)
    return {
        boot=boot,uptime=uptime,source="eth0_0",pon_state=51,
        ethernet_mbps=10000,observed={pon=true,host=true},
        eth={
            RxGoodBytes=tostring(bytes),
            TxGoodBytes=tostring(bytes*2),
            RxFCSErrorPkts=counters[1],
            RxOverflowError=counters[2],
            RxDroppedPkts=counters[3],
            TxDroppedPkts=counters[4],
        },
    }
end
local parser=native.parsers.ethtool
local raw=[[NIC statistics:
  RxGoodBytes: 100000
  TxGoodBytes: 200000
  RxFCSErrorPkts: 40
  RxOverflowError: 12
  RxDroppedPkts: 150
  TxDroppedPkts: 90
  RxBadBytes: 888
  login_password: PRIVATE
]]
local parsed=assert(parser(raw))
same(parsed.RxFCSErrorPkts,"40","native_fcs")
same(parsed.RxOverflowError,"12","native_overflow")
same(parsed.RxDroppedPkts,"150","native_rx_drop")
same(parsed.TxDroppedPkts,"90","native_tx_drop")
same(parsed.RxBadBytes,nil,"unrequested_raw_dropped")
same(parsed.login_password,nil,"no_secret_copied")
local bad,why=parser("RxGoodBytes: 10\nRxFCSErrorPkts: 4\nRxFCSErrorPkts: 8\n")
same(bad,nil,"duplicate_rejected")
same(why,"ambiguous_eth_counter","duplicate_reason")
bad,why=parser("RxGoodBytes: 10\nRxDroppedPkts: 18446744073709551616\n")
same(bad,nil,"out_of_range_rejected")
same(why,"invalid_eth_counter","range_error")
local boot="11111111-2222-4333-8444-555555555555"
local state=assert(sampler.new())
local function ingest(t,b,values,counters)
    return assert(sampler.ingest_selected(state,snapshot(b,t,values,counters)))
end
ingest(100,boot,100000,{"40","12","150","90"})
local first=assert(sampler.recent(state,"samples",1))[1]
same(first.rx_fcs_error_delta,nil,"initial_counter_no_false_zero")
ingest(160,boot,350000,{"42","12","155","94"})
local sampled=assert(sampler.recent(state,"samples",2))[2]
same(sampled.status,"valid_interval","valid_rate_window")
same(sampled.rx_fcs_error_delta,2,"fcs_two")
same(sampled.rx_overflow_delta,0,"overflow_zero_measured")
same(sampled.rx_drop_delta,5,"rx_drop_five")
same(sampled.tx_drop_delta,4,"tx_drop_four")
local projected=assert(exporter.project(state,"hour",100,"local_runtime"))
same(projected.samples[2].rx_fcs_error_delta,2,"public_fcs_delta")
same(projected.samples[2].tx_drop_delta,4,"public_tx_drop_delta")
same(shape.validate(projected),true,"strict_cross_process_validator_accepts")
local bad_public=assert(exporter.project(state,"hour",100,"local_runtime"))
bad_public.samples[2].rx_drop_delta=-1
same(shape.validate(bad_public),nil,"reject_negative_drop")
bad_public.samples[2].rx_drop_delta=1.25
same(shape.validate(bad_public),nil,"reject_fraction")
bad_public.samples[2].rx_drop_delta=1000000001
same(shape.validate(bad_public),nil,"reject_oversized_delta")
bad_public.samples[2].rx_drop_delta=5
bad_public.samples[2].status="baseline"
same(shape.validate(bad_public),nil,"reject_delta_without_valid_interval")

-- A counter regression omits only that particular counter: it is not a
-- packet-error recovery, a lifetime rate, or a negative number.
ingest(220,boot,700000,{"2","14","151","100"})
sampled=assert(sampler.recent(state,"samples",1))[1]
same(sampled.rx_fcs_error_delta,nil,"counter_reset_not_zero")
same(sampled.rx_overflow_delta,2,"valid_other_counter")
same(sampled.rx_drop_delta,nil,"rx_drop_regression_unavailable")
same(sampled.tx_drop_delta,6,"tx_drop_still_valid")

-- Missing kernel counter leaves the field absent rather than converting
-- no observation into a misleading healthy zero.
ingest(280,boot,800000,{nil,nil,nil,nil})
sampled=assert(sampler.recent(state,"samples",1))[1]
same(sampled.rx_fcs_error_delta,nil,"missing_fcs_not_zero")
same(sampled.rx_drop_delta,nil,"missing_drop_not_zero")

-- A new boot ID closes the epoch: no counter delta spans resets/reboots.
local reboot="22222222-3333-4444-8555-666666666666"
ingest(2,reboot,100,{"0","0","0","0"})
sampled=assert(sampler.recent(state,"samples",1))[1]
same(sampled.status,"reboot","new_epoch")
same(sampled.rx_fcs_error_delta,nil,"no_cross_boot_error_delta")
same(sampled.tx_drop_delta,nil,"no_cross_boot_drop_delta")

local receipt=assert(exporter.project(state,"hour",100,"local_runtime"))
same(shape.validate(receipt),true,"postreboot_contract_still_valid")
same(receipt.actual_isp_uptime_unverified,true,"not_isp_uptime")
same(receipt.optics_history_unavailable,true,"optics_not_claimed")
same(checks>=30,true,"coverage_floor")
if arg[2]=="emit_json" then
    local demo=assert(sampler.new())
    local function put(t,bytes,err)
        local sample=snapshot(boot,t,bytes,err)
        return assert(sampler.ingest_selected(demo,sample))
    end
    put(100,100000,{"40","12","150","90"})
    put(160,350000,{"42","12","155","94"})
    put(220,700000,{"43","13","160","95"})
    local json=assert(exporter.export_json(demo,"hour",100,"local_runtime"))
    print("AOTT_V3R4_INTEGRITY_JSON="..json)
end
print("AOTT_V3R4_RAM_ETH_INTEGRITY_PASS assertions="..checks)
