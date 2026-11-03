-- H-022 operator-independent offline lock fixture.
-- Actual extracted vendor MIPS nixio is used. No ONU or PON access.
local root=assert(arg[1],"Extracted vendor Lua rootfs required")
package.path=root.."/usr/lib/lua/?.lua;"..
    root.."/usr/lib/lua/?/init.lua;"..package.path
package.cpath=root.."/usr/lib/lua/?.so;"..package.cpath
local source=assert(arg[2],"H-022 module file required")
local mode=assert(arg[3],"Test mode required")
local directory=assert(arg[4],"Private test directory required")
local lock=assert(loadfile(source))()
local function report(ok,label)
    if not ok then error("H022_LOCK_FIXTURE_FAILED:"..label) end
end
if mode=="own" or mode=="hold" or mode=="hold_exit" then
    local handle,metadata=assert(lock.acquire(directory))
    report(metadata.status=="advisory_owner_acquired","owner")
    report(metadata.cross_process_fcntl_lock==true,"actual_kernel_lock")
    report(assert(lock.status(handle)).cross_process_lock_held,"status")
    print("AOTT_H022_LOCK_ACQUIRED")
    io.stdout:flush()
    local duplicate,why=lock.acquire(directory)
    report(duplicate==nil and why=="collector_already_owned_in_process",
           "no_second_owner_same_process")
    if mode=="hold" or mode=="hold_exit" then
        io.read("*l")
    end
    if mode=="hold_exit" then
        print("AOTT_H022_EXIT_WITH_FD_LOCK")
        os.exit(0)
    end
    local done=assert(lock.release(handle))
    report(done.lock_file_is_never_unlinked,"stable_inode")
    report(lock.status(handle)==nil,"closed_token")
    report(lock.release(handle)==nil,"double_release_refused")
    print("AOTT_H022_LOCK_RELEASED")
elseif mode=="try" then
    local handle,why=lock.acquire(directory)
    if handle then
        print("AOTT_H022_TRY_GRANTED")
        assert(lock.release(handle))
    else
        report(why=="collector_held_by_other_process","expected_busy")
        print("AOTT_H022_TRY_BUSY")
    end
elseif mode=="reject_path" then
    local handle,why=lock.acquire(directory)
    report(handle==nil and why=="disallowed_lock_directory",
           "path_policy")
    print("AOTT_H022_REJECTED_PATH")
elseif mode=="reject_directory" then
    local handle,why=lock.acquire(directory)
    report(handle==nil and why=="unsafe_collector_directory",
           "dir_permissions")
    print("AOTT_H022_REJECTED_DIRECTORY")
elseif mode=="reject_lock" then
    local handle,why=lock.acquire(directory)
    report(handle==nil and why=="unsafe_lock_file",
           "lock_permissions_or_symlink")
    print("AOTT_H022_REJECTED_LOCK")
else
    error("Unexpected test mode")
end
