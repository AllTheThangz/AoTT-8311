#!/usr/bin/env python3
"""Passive PRX126 datapath sampler: fixed read-only SSH commands, no writes."""
import argparse
import json
import re
import subprocess
import time

# This command is constant and accepts no data from the target string.
# No PON identity, MAC, boot env, credentials, flash or management config.
REMOTE = r"""
LC_ALL=C
awk '/^cpu / {t=0; for (i=2;i<=NF;i++) t+=$i;
  printf "cpu_total=%d\ncpu_idle=%d\n",t,$5+$6;exit}' /proc/stat
printf 'link_speed='; cat /sys/class/net/eth0_0/speed
printf 'carrier='; cat /sys/class/net/eth0_0/carrier
printf 'rx_errors='; cat /sys/class/net/eth0_0/statistics/rx_errors
printf 'tx_errors='; cat /sys/class/net/eth0_0/statistics/tx_errors
printf 'rx_dropped='; cat /sys/class/net/eth0_0/statistics/rx_dropped
printf 'tx_dropped='; cat /sys/class/net/eth0_0/statistics/tx_dropped
printf 'thermal0='; cat /sys/class/thermal/thermal_zone0/temp
printf 'thermal1='; cat /sys/class/thermal/thermal_zone1/temp
printf 'datapath_module='; grep -c '^gwdpa_dpm ' /proc/modules
/usr/bin/timeout -k 1 4 /usr/sbin/ethtool -S eth0_0 2>/dev/null |
  awk '$1=="RxGoodBytes:" {print "mac_rx_good_bytes=" $2}
       $1=="TxGoodBytes:" {print "mac_tx_good_bytes=" $2}'
"""
FIELDS = frozenset({
    "cpu_total","cpu_idle","link_speed","carrier",
    "rx_errors","tx_errors","rx_dropped","tx_dropped",
    "thermal0","thermal1","datapath_module",
    "mac_rx_good_bytes","mac_tx_good_bytes",
})

class ProbeError(ValueError):
    pass

def parse(raw):
    if len(raw)>4096: raise ProbeError("output_limit")
    result={}
    for line in raw.splitlines():
        if not re.fullmatch(r"[a-z_0-9]{2,40}=[0-9]{1,22}",line):
            raise ProbeError("invalid_sample")
        name,value=line.split("=",1)
        if name not in FIELDS or name in result: raise ProbeError("untrusted_field")
        result[name]=int(value)
    for name in ("cpu_total","cpu_idle","link_speed","carrier"):
        if name not in result: raise ProbeError("incomplete_sample")
    return result

def difference(a,b,key):
    if key not in a or key not in b or b[key]<a[key]: return None
    return b[key]-a[key]

def summarize(a,b,elapsed):
    if elapsed<=0 or elapsed>90: raise ProbeError("invalid_interval")
    total=difference(a,b,"cpu_total")
    idle=difference(a,b,"cpu_idle")
    busy=round(100*(1-idle/total),1) if total and idle is not None and idle<=total else None
    def rate(direction):
        d=difference(a,b,"mac_"+direction+"_good_bytes")
        return round(8*d/elapsed/1000000,3) if d is not None else None
    return {
      "mode":"passive_readonly",
      "interval_seconds":round(elapsed,2),
      "cpu_busy_percent":busy,
      "ethernet_mbps":b["link_speed"],
      "ethernet_carrier_stable":a["carrier"]==b["carrier"]==1,
      "observed_from_router_mbps":rate("rx"),
      "observed_to_router_mbps":rate("tx"),
      "error_drop_deltas":{
          name:difference(a,b,name) for name in
          ("rx_errors","tx_errors","rx_dropped","tx_dropped")
      },
      "thermal_c":[
          round(b[key]/1000,2) if key in b else None
          for key in ("thermal0","thermal1")
      ],
      "vendor_datapath_module_detected":b.get("datapath_module")==1,
      "offload_for_all_packets_proven":False,
      "isp_line_speed_proven":False,
      "live_changes_made":False,
      "note":"No synthetic traffic; hardware MAC counter rates may be idle. "
             "Offload and ISP bandwidth require a separate controlled WAN test."
    }

def remote_sample(target):
    if (not re.fullmatch(r"[A-Za-z0-9_.@:-]{1,180}",target)
            or target.startswith("-")):
        raise ProbeError("invalid_target")
    argv=["ssh","-o","BatchMode=yes","-o","StrictHostKeyChecking=yes",
          "-o","ConnectTimeout=6",target,REMOTE]
    r=subprocess.run(argv,text=True,capture_output=True,timeout=13,check=False)
    if r.returncode!=0: raise ProbeError("ssh_probe_unavailable")
    return parse(r.stdout)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target",required=True,help="authorized SSH target; not printed")
    p.add_argument("--seconds",type=int,default=10)
    a=p.parse_args()
    if not 5<=a.seconds<=60: p.error("seconds must be 5..60")
    try:
        first=remote_sample(a.target)
        begin=time.monotonic()
        time.sleep(a.seconds)
        second=remote_sample(a.target)
        print(json.dumps(summarize(first,second,time.monotonic()-begin),
                         indent=2,sort_keys=True))
    except (OSError,subprocess.TimeoutExpired,ProbeError) as e:
        p.exit(2,"Read-only probe failed: "+type(e).__name__+"\n")
if __name__=="__main__": main()
