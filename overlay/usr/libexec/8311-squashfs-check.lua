-- Maint3 bounded SquashFS v4/XZ superblock preflight. This is deliberately not
-- a decompressor or a bootability claim; the written bank must mount read-only
-- and its pinned boot/runtime files must be read before it becomes selectable.
local path, extent, exact = arg[1], tonumber(arg[2]), arg[3]
local function reject(reason)
    io.stderr:write('SquashFS preflight failed: ', reason, '\n')
    os.exit(1)
end
if not path or not extent or extent < 96 or extent > 33554432 then reject('invalid extent') end
local f = io.open(path, 'rb')
if not f then reject('cannot open image') end
local h = f:read(96)
if not h or #h ~= 96 then reject('short superblock') end
local function u16(o) local a,b=h:byte(o+1,o+2); return a+b*256 end
local function u32(o) local a,b,c,d=h:byte(o+1,o+4); return a+b*256+c*65536+d*16777216 end
local function offset(o, optional)
    local lo,hi=u32(o),u32(o+4)
    if optional and lo==4294967295 and hi==4294967295 then return nil end
    if hi~=0 or lo<96 or lo>=u32(40) then reject('table offset outside used image') end
    return lo
end
if h:sub(1,4)~='hsqs' or u16(28)~=4 or u16(30)~=0 then reject('unsupported filesystem version') end
if u16(20)~=4 then reject('profile requires XZ compression') end
local block,log,flags,inodes,fragments,ids=u32(12),u16(22),u16(24),u32(4),u32(16),u16(26)
if log<12 or log>20 or block~=2^log then reject('block size and block log do not match') end
if flags>=4096 then reject('unsupported feature flags') end
if inodes<1 or inodes>1048576 or fragments>inodes or ids<1 then reject('invalid inode, fragment, or ID count') end
local used=u32(40)
if u32(44)~=0 or used<96 or used>extent then reject('bytes_used outside extent') end
local id=offset(48,false)
local xattr=offset(56,true)
local inode=offset(64,false)
local directory=offset(72,false)
local fragment=offset(80,true)
local lookup=offset(88,true)
if inode>=directory or directory>id then reject('invalid metadata table ordering') end
if id+math.ceil(ids/2048)*8>used then reject('truncated ID table index') end
if fragments>0 and (not fragment or fragment<directory or fragment+math.ceil(fragments/512)*8>used) then reject('invalid fragment table index') end
if math.floor(flags/128)%2==1 and not lookup then reject('missing export table') end
if lookup and (lookup<directory or lookup+math.ceil(inodes/1024)*8>used) then reject('invalid export table index') end
if xattr and xattr+16>used then reject('truncated xattr table header') end
local rootlo,roothi=u32(32),u32(36)
local rootblock=math.floor(rootlo/65536)+roothi*65536
if rootlo%65536>=8192 or rootblock>=directory-inode then reject('root inode reference outside inode table') end
if exact=='exact' then
    if extent-used>4095 then reject('excessive trailing data') end
    if not f:seek('set',used) then reject('cannot seek padding') end
    local padding=f:read(extent-used) or ''
    if #padding~=extent-used or padding:find('[^%z]') then reject('nonzero or truncated padding') end
end
if not f:close() then reject('close failed') end
io.write(string.format('%.0f\n',used))
