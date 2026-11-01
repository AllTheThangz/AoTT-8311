-- Test the real vendor nixio/fs and jsonc modules on disposable storage.
-- No production ptconf, route, network or PON files are accessed.
local module_path = assert(arg[1], "monitor_store module path")
local scratch = assert(arg[2], "synthetic private scratch directory")
local rootfs = arg[3]
if rootfs then
    package.path = rootfs .. "/usr/lib/lua/?.lua;" ..
                   rootfs .. "/usr/lib/lua/?/init.lua;" .. package.path
    package.cpath = rootfs .. "/usr/lib/lua/?.so;" .. package.cpath
end
local fs = require "nixio.fs"
local M = assert(loadfile(module_path))()
M.root = scratch .. "/private-record"
M.mounts_file = scratch .. "/fake-mounts"
assert(fs.writefile(M.mounts_file, "ubi0:ptconf /ptconf ubifs rw 0 0\n"))
assert(fs.chmod(M.mounts_file, 600))
local record = {
    schema=1, log_remote="1",log_ip="collector.example.com",
    log_port="5514", log_proto="tcp", aott_metrics="1",
    aott_metrics_client="192" .. ".0.2.40",
    aott_metrics_sha256=string.rep("a",64)
}
assert(M.valid(record))
assert(M.read() == nil, "Absent durable store must fail closed")
local saved, why = M.write(record)
assert(saved, why)
local fetched, error = M.read()
assert(fetched, error)
assert(fetched.aott_metrics_sha256 == record.aott_metrics_sha256)
assert(fetched.log_ip == record.log_ip)
local file = M.root .. "/config.json"
local original = fs.readfile(file)
assert(original and #original < 2048)
assert(original == M.canonical(record))
assert(fs.lstat(file).modedec == 600)
assert(fs.lstat(M.root).modedec == 700)
assert(M.same_live({
    log_remote=record.log_remote,log_ip=record.log_ip,
    log_port=record.log_port, log_proto=record.log_proto,
    aott_metrics=record.aott_metrics,
    aott_metrics_client=record.aott_metrics_client,
    aott_metrics_sha256=record.aott_metrics_sha256
}))
record.aott_metrics="0"
record.aott_metrics_sha256=""
assert(M.write(record))
assert(M.read().aott_metrics == "0")
assert(not M.same_live({
    log_remote="1",log_ip="collector.example.com",
    log_port="5514",log_proto="tcp",aott_metrics="1",
    aott_metrics_client="192" .. ".0.2.40",
    aott_metrics_sha256=string.rep("a",64)
}))
local path=M.root .. "/config.json"
assert(fs.chmod(path,644))
assert(M.read() == nil, "World-readable durable file must fail closed")
assert(fs.chmod(path,600))
assert(fs.writefile(M.mounts_file, "ubi0:other /ptconf ubifs rw 0 0\n"))
assert(M.read()==nil, "Unexpected mount source must fail closed")
assert(fs.writefile(M.mounts_file, "ubi0:ptconf /ptconf ubifs rw 0 0\n"))
assert(M.read().aott_metrics=="0")
assert(fs.unlink(path))
assert(fs.symlink("/dev/null",path))
assert(M.read()==nil,"Symlink must fail closed")
assert(M.write(record)==nil,"Symlink overwrite must be rejected")
assert(fs.unlink(path))
assert(M.write(record))
local original=fs.readfile(path)
assert(fs.writefile(path,original:gsub('"log_port":"5514"', '"log_port":"5514","log_port":"5514"')))
assert(M.read()==nil, "Duplicate JSON key must fail closed")
assert(fs.writefile(path,original))
assert(M.read().log_port=="5514")
print("PERSISTENT_STORE_VENDOR_RUNTIME_PASS")
