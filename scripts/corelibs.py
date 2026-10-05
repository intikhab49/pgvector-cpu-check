#!/usr/bin/env python3
"""Maps a crash PC to <library, offset, function, instruction> using only a core file and the image's files.

QEMU's guest cores have no NT_FILE note and leave out read-only code pages, so gdb can neither list the
shared libraries nor disassemble at the PC. The dynamic loader's link_map list lives in writable memory,
which the core does contain:  struct link_map { l_addr; char *l_name; ElfW(Dyn) *l_ld; l_next; l_prev; }.
For every "/....so" path string in the core we look for pointers to it (l_name) and accept the entry only if
l_ld - l_addr equals that library's real .dynamic address (read from the file in ROOTFS). That check makes
false positives practically impossible. The instruction is then disassembled from the library file itself.

Usage: scripts/corelibs.py ARCH CORE ROOTFS PC [EXECUTABLE [PKGLIBDIR]]
Prints one line: <instruction>\t<function+0xoff> in <library> (offset 0x...)"""
import bisect
import functools
import pathlib
import re
import struct
import subprocess
import sys

arch, core_path, rootfs, pc = sys.argv[1], sys.argv[2], sys.argv[3].rstrip("/"), int(sys.argv[4], 16)
OBJDUMP = "objdump" if arch == "amd64" else "aarch64-linux-gnu-objdump"
NM = "nm" if arch == "amd64" else "aarch64-linux-gnu-nm"

data = open(core_path, "rb").read()
phoff, = struct.unpack_from("<Q", data, 0x20)
phentsize, phnum = struct.unpack_from("<HH", data, 0x36)
segs = []  # (vaddr, offset, filesz)
for i in range(phnum):
    p_type, _flags, p_offset, p_vaddr, _paddr, p_filesz = struct.unpack_from("<IIQQQQ", data, phoff + i * phentsize)
    if p_type == 1 and p_filesz:
        segs.append((p_vaddr, p_offset, p_filesz))
segs.sort()


def read(addr, n):
    for v, o, sz in segs:
        if v <= addr and addr + n <= v + sz:
            return data[o + addr - v:o + addr - v + n]
    return None


def read_parts(addr, n):
    """Bytes of [addr, addr+n) that the core really holds, as (offset_in_range, bytes) pieces: the range may
    span several QEMU segments, and a truncated core simply lacks the tail."""
    parts = []
    for v, o, sz in segs:
        lo, hi = max(addr, v), min(addr + n, v + sz)
        if lo < hi:
            chunk = data[o + lo - v:o + hi - v]  # shorter than hi-lo if the file is truncated here
            if chunk:
                parts.append((lo - addr, chunk))
    return parts


@functools.lru_cache(maxsize=None)
def dynamic_vaddr_and_end(path):
    out = subprocess.run(["readelf", "-lW", path], capture_output=True, text=True).stdout
    dyn = re.search(r"^\s*DYNAMIC\s+0x[0-9a-f]+\s+(0x[0-9a-f]+)", out, re.M)
    ends = [int(v, 16) + int(m, 16) for v, m in re.findall(r"^\s*LOAD\s+0x[0-9a-f]+\s+(0x[0-9a-f]+)\s+0x[0-9a-f]+\s+0x[0-9a-f]+\s+(0x[0-9a-f]+)", out, re.M)]
    return (int(dyn.group(1), 16) if dyn else None), (max(ends) if ends else 0)


libs = {}  # path -> (l_addr, size)
for v, o, sz in segs:
    seg = data[o:o + sz]
    for m in re.finditer(rb"/[\x21-\x7e]{1,255}?\.so(?:\.[\w.]+)?\x00", seg):
        path = m.group(0)[:-1].decode()
        if path in libs:
            continue
        needle = struct.pack("<Q", v + m.start())
        for v2, o2, sz2 in segs:
            seg2 = data[o2:o2 + sz2]
            start = 0
            while (hit := seg2.find(needle, start)) != -1:
                start = hit + 1
                if hit < 8 or (v2 + hit) % 8:
                    continue
                l_addr, = struct.unpack_from("<Q", seg2, hit - 8)
                l_ld_raw = seg2[hit + 8:hit + 16]
                if len(l_ld_raw) < 8 or l_addr % 4096:
                    continue
                l_ld, = struct.unpack("<Q", l_ld_raw)
                dyn, size = dynamic_vaddr_and_end(rootfs + path)
                if dyn is not None and l_ld - l_addr == dyn:
                    libs[path] = (l_addr, size)
                    break
            if path in libs:
                break

# The main executable: its link_map name is empty, so place it with the ELF auxiliary vector instead
# (NT_AUXV note: AT_ENTRY - e_entry = load base).
exe = sys.argv[5] if len(sys.argv) > 5 else ""
if exe:
    for i in range(phnum):
        p_type, _f, p_offset, _v, _p, p_filesz = struct.unpack_from("<IIQQQQ", data, phoff + i * phentsize)
        if p_type != 4:  # PT_NOTE
            continue
        pos, end = p_offset, p_offset + p_filesz
        while pos + 12 <= end:
            namesz, descsz, ntype = struct.unpack_from("<III", data, pos)
            desc = pos + 12 + ((namesz + 3) & ~3)
            if ntype == 6:  # NT_AUXV
                auxv = dict(struct.unpack_from("<QQ", data, desc + j) for j in range(0, descsz - 15, 16))
                hdr = subprocess.run(["readelf", "-hW", rootfs + exe], capture_output=True, text=True).stdout
                e_entry = re.search(r"Entry point address:\s+(0x[0-9a-f]+)", hdr)
                if 9 in auxv and e_entry:
                    libs[exe] = (auxv[9] - int(e_entry.group(1), 16), dynamic_vaddr_and_end(rootfs + exe)[1])
            pos = desc + ((descsz + 3) & ~3)

for p, (a, size) in sorted(libs.items(), key=lambda kv: kv[1][0]):
    print(f"MAP	0x{a:x}-0x{a + size:x}	{p}", file=sys.stderr)
print(f"MAP	core segments: " + " ".join(f"0x{v:x}+0x{sz:x}" for v, _o, sz in segs if v <= pc + (1 << 24) and pc - (1 << 24) <= v + sz), file=sys.stderr)
hit = next(((p, a) for p, (a, size) in libs.items() if a <= pc < a + size), None)

# Fallback for libraries whose link_map entry was cut off (QEMU 7.2 truncates large cores, and a dlopen()ed
# extension's entry is allocated late): match each candidate library's PT_LOAD layout, page by page, against
# the core's segment starts. Only the right file at the right base fits all of its segments.
if not hit:
    starts, ranges = set(), []
    for i in range(phnum):
        p_type, _f, _o, p_vaddr, _p, _fs, p_memsz = struct.unpack_from("<IIQQQQQ", data, phoff + i * phentsize)
        if p_type == 1:
            starts.add(p_vaddr)
            ranges.append((p_vaddr, p_vaddr + p_memsz))
    pc_range = next(((a, b) for a, b in sorted(ranges) if a <= pc < b), None)
    pc_seg = pc_range[0] if pc_range else None
    pkglib = sys.argv[6] if len(sys.argv) > 6 else ""
    candidates = []
    for d in filter(None, [pkglib, "/usr/lib", "/usr/local/lib", "/lib", "/usr/lib/aarch64-linux-gnu", "/usr/lib/x86_64-linux-gnu"]):
        root = pathlib.Path(rootfs + d)
        if root.is_dir():
            candidates += [p.resolve() for p in root.rglob("*.so*") if p.is_file() and not p.is_symlink()]
    candidates = sorted(set(candidates))
    matches = []
    for lib_path in candidates:
        out = subprocess.run(["readelf", "-lW", str(lib_path)], capture_output=True, text=True).stdout
        loads = [(int(o, 16), int(v, 16), int(fs, 16), int(m, 16), fl) for o, v, fs, m, fl in re.findall(
            r"^\s*LOAD\s+(0x[0-9a-f]+)\s+(0x[0-9a-f]+)\s+0x[0-9a-f]+\s+(0x[0-9a-f]+)\s+(0x[0-9a-f]+)\s+([RWE ]+?)\s+0x", out, re.M)]
        exec_loads = [(v, m) for _o, v, _fs, m, fl in loads if "E" in fl]
        if not exec_loads or pc_seg is None:
            continue
        ev, em = exec_loads[0]
        base = pc_seg - (ev & ~0xfff)
        # layout: page-aligned base, PC inside the code segment, every segment start present in the core
        if base % 4096 or not (base + ev <= pc < base + ev + em) \
                or not all(base + (v & ~0xfff) in starts for _o, v, _fs, _m, _fl in loads):
            continue
        # contents: initial bytes of the writable segment, file vs core (relocated pointers will differ)
        blob = lib_path.read_bytes()
        same = total = 0
        for o, v, fs, _m, fl in loads:
            if "W" not in fl or not fs:
                continue
            for rel, chunk in read_parts(base + v, fs):
                ref = blob[o + rel:o + rel + len(chunk)]
                same += sum(1 for a, b in zip(chunk, ref) if a == b)
                total += len(ref)
        score = same / total if total >= 256 else 0.0
        print(f"LAYOUT\t{str(lib_path)[len(rootfs):]}\tbase 0x{base:x}\tdata match {same}/{total} = {score:.2f}", file=sys.stderr)
        matches.append((score, str(lib_path)[len(rootfs):], base))
    matches.sort(reverse=True)
    if matches and matches[0][0] >= 0.5 and (len(matches) == 1 or matches[0][0] - matches[1][0] >= 0.15):
        hit = (matches[0][1], matches[0][2])
        print(f"LAYOUT\tchosen {hit[0]} (data match {matches[0][0]:.2f}, next {matches[1][0] if len(matches) > 1 else 0:.2f})", file=sys.stderr)
    elif matches:
        print(f"?\tPC 0x{pc:x} ambiguous by layout and data: " + ", ".join(f"{m[1]}={m[0]:.2f}" for m in matches[:5]))
        sys.exit(0)
if not hit:
    print(f"?\tPC 0x{pc:x} not in any of {len(libs)} recovered libraries or the executable")
    sys.exit(0)
path, base = hit
off = pc - base
lib = rootfs + path
syms = []
for flag in ("-D", ""):
    out = subprocess.run([NM, "--defined-only"] + ([flag] if flag else []) + [lib], capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1].lower() in "tw":
            syms.append((int(parts[0], 16), parts[2]))
syms.sort()
i = bisect.bisect_right([s[0] for s in syms], off) - 1
func = f"{syms[i][1]}+0x{off - syms[i][0]:x}" if i >= 0 else "?"
dis = subprocess.run([OBJDUMP, "-d", "--no-show-raw-insn", f"--start-address=0x{off:x}", f"--stop-address=0x{off + 16:x}", lib],
                     capture_output=True, text=True).stdout
insn = next((l.split("\t", 1)[1].strip() for l in dis.splitlines() if re.match(rf"\s*{off:x}:", l) and "\t" in l), "?")
print(f"{insn}\t{func} in {path} (offset 0x{off:x})")
