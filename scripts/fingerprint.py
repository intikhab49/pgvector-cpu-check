#!/usr/bin/env python3
"""Static fingerprint of PostgreSQL extension libraries: which instruction-set extensions each
library uses, in how many of its functions, and whether it carries CPU-dispatch machinery.

A library compiled with a global -march/target-cpu flag uses the newer instructions all over
(memcpy-like loops, hashing, sorting). A library that dispatches at runtime keeps them inside a
few kernels and calls cpuid / an IFUNC resolver / Rust's std_detect first.

Usage: scripts/fingerprint.py ARCH LIBDIR > fingerprint.tsv
Columns: file, functions, then per class "name=functions_using_it", dispatch evidence, compiler, verdict."""
import pathlib
import re
import subprocess
import sys

arch, libdir = sys.argv[1], pathlib.Path(sys.argv[2])
OBJDUMP = "objdump" if arch == "amd64" else "aarch64-linux-gnu-objdump"

# Instruction classes, matched against one disassembled instruction (mnemonic + operands).
X86 = {
    "avx512": re.compile(r"%zmm|%k[0-7]\b|\{%k|vpternlog|vpermt2|vcompress|vexpand|vpopcnt[bwdq]"),
    "avx2": re.compile(r"\bvp\w+\s.*%ymm|\bvperm(q|d|ps|pd|2i128)\b|\bvpbroadcast|\bvinserti128|\bvextracti128|\bvpgather|\bvgather"),
    "avx": re.compile(r"%ymm|\bv(add|sub|mul|div|max|min|and|or|xor|blend|shuf|unpck|movap|movup|broadcastss|sqrt|cvt)\w*\s"),
    "fma": re.compile(r"\bvfn?m(add|sub)"),
    "f16c": re.compile(r"\bvcvt(ph2ps|ps2ph)\b"),
    # tzcnt/lzcnt are left out: CPUs without BMI/ABM decode them as rep-bsf/bsr instead of faulting.
    "bmi": re.compile(r"\b(andn|bextr|blsi|blsr|blsmsk|pdep|pext|shlx|shrx|sarx|rorx)\b"),
    "popcnt": re.compile(r"\bpopcnt\b"),
    "sse4": re.compile(r"\b(pminsd|pmaxsd|pmulld|ptest|pblendvb|blendvps|roundps|roundss|pcmpeqq|pextr[bdq]|pinsr[bdq]|crc32[bwlq]?|pcmpgtq|pcmp[ei]str[im])\b"),
}
ARM = {
    "sve": re.compile(r"\bz\d+\.[bhsdq]\b|\bp\d+/[mz]\b|\bwhilelo\b|\bptrue\b"),
    # FEAT_FP16 = half-precision ARITHMETIC. Conversions (fcvt/fcvtl/fcvtn between h and s) are ARMv8.0 base.
    "fp16": re.compile(r"\bf(?!cvt)\w+\s.*\bv\d+\.[48]h\b|\bf(add|sub|mul|mla|mls|max|min|div|abs|neg|sqrt|cmp|cmpe|madd|msub|nmul|rint\w)\s+h\d+"),
    "dotprod": re.compile(r"\b[su]dot\b"),
    "lse": re.compile(r"\b(ldadd|ldclr|ldeor|ldset|ldsmax|ldsmin|ldumax|ldumin|swp|cas|casp)(a|l|al)?[bh]?\b"),
    "crypto": re.compile(r"\b(aes[ed]|aesi?mc|sha1[chmps]\w*|sha256\w*|sha512\w*|pmull2?)\b"),
    "rcpc": re.compile(r"\bldapr\w*\b"),
}
CLASSES = X86 if arch == "amd64" else ARM
# Highest requirement first. QEMU models in the dynamic test: Nehalem < SandyBridge < IvyBridge < Haswell.
FLOOR = [("avx512", "AVX-512 (fails on Haswell and every AMD before Zen 4)"), ("avx2", "AVX2 (Haswell)"),
         ("fma", "FMA (Haswell)"), ("f16c", "F16C (IvyBridge)"), ("avx", "AVX (SandyBridge)"), ("bmi", "BMI (Haswell)")] \
    if arch == "amd64" else \
        [("sve", "SVE (Neoverse V1/Graviton3+; not Pi, Graviton2, Ampere Altra)"), ("fp16", "ARMv8.2 FP16 (not Pi 3/4)"),
         ("dotprod", "ARMv8.2 dot product (not Pi 3/4)"), ("rcpc", "ARMv8.3 RCpc"), ("lse", "ARMv8.1 LSE atomics (not Pi 3/4)")]
FUNC_RE = re.compile(r"^[0-9a-f]+ <(.+)>:$")
DISPATCH_NAME = re.compile(r"(?i)avx|fma|f16c|sse|bmi|popcnt|neon|sve|fp16|asimd|::v[234]\b|_v[234]\b|x86[_-]64[_-]v"
                           r"|haswell|skylake|icelake|znver|sapphire|cascade|_resolver|ifunc")


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace").stdout


def fingerprint(path):
    funcs = {}
    current = None
    cpuid = 0
    proc = subprocess.Popen([OBJDUMP, "-d", "-C", "--no-show-raw-insn", str(path)], stdout=subprocess.PIPE,
                            text=True, errors="replace")
    for line in proc.stdout:
        line = line.rstrip("\n")
        m = FUNC_RE.match(line)
        if m:
            current = m.group(1)
            funcs[current] = set()
            continue
        if current is None or "\t" not in line:
            continue
        insn = line.split("\t", 1)[1]
        if insn.startswith("cpuid"):
            cpuid += 1
        for name, rx in CLASSES.items():
            if rx.search(insn):
                funcs[current].add(name)
    # libgcc's outline-atomics helpers (__aarch64_ldadd4_acq_rel, ...) pick LSE at runtime themselves.
    funcs = {f: c for f, c in funcs.items() if not f.startswith("__aarch64_")}
    counts = {name: sum(1 for c in funcs.values() if name in c) for name in CLASSES}

    evidence = []
    dyn = run(["readelf", "--dyn-syms", "-W", str(path)])
    if "IFUNC" in dyn:
        evidence.append("ifunc")
    if "__cpu_indicator_init" in dyn or "__cpu_model" in dyn:
        evidence.append("gcc-cpu-supports")
    proc.wait()
    if cpuid:
        evidence.append(f"cpuid x{cpuid}")
    if arch == "arm64" and re.search(r"getauxval|AT_HWCAP|id_aa64", run(["strings", "-a", str(path)])):
        evidence.append("hwcap")
    strs = run(["strings", "-a", "-n", "8", str(path)])
    if "std_detect" in strs or "is_x86_feature_detected" in strs or "is_aarch64_feature_detected" in strs:
        evidence.append("rust-std_detect")
    if re.search(r"multiversion|target_feature_dispatch", strs):
        evidence.append("multiversion")

    comment = run(["readelf", "-p", ".comment", str(path)])
    compilers = sorted(set(re.findall(r"(GCC: \([^)]*\) [\d.]+|clang version [\d.]+|rustc version [\d.]+[^\s]*|Ubuntu clang[^\n]*)", comment)))
    producer = re.search(r"DW_AT_producer\s*:.*?(-march=\S+|-mcpu=\S+|target-cpu=\S+)", run(["readelf", "--debug-dump=info", str(path)])[:2_000_000])
    flags = producer.group(1) if producer else ""
    for m in re.finditer(r"-(march|mcpu)=[\w.+-]+|target-cpu=\w+|target-feature=[+\w,-]+", strs):
        flags = flags or m.group(0)

    # Verdict: the lowest CPU this library needs. Runtime dispatch guards a handful of kernels
    # (pgvector: ~2-6 functions with target attributes); a class found in more functions than that,
    # or in any function when there is no dispatch at all, came from a global compiler flag.
    # Calibrated against the dynamic results: with dispatch present, the deliberately multiversioned kernels
    # are named for their target (pgvector BitHammingDistanceAvx512Popcount, VectorChord simd::...::v4::...).
    # Set those aside; a newer instruction in ANY remaining function means a global -march/target-cpu.
    # In stripped libraries a dispatched static kernel is attributed to the nearest exported symbol, so name
    # exclusion alone is not enough: with dispatch present, a class must also cover >= 5% of the regions to
    # count as a global flag. Without any dispatch machinery, a single use sets the floor. libgcc's
    # outline-atomics helpers (LSE behind a runtime check) collapse into 1-2 unnamed regions when stripped.
    unguarded = {f: c for f, c in funcs.items() if not (evidence and DISPATCH_NAME.search(f))}
    def is_floor(cls):
        n = sum(1 for c in unguarded.values() if cls in c)
        if cls == "lse" and n <= 2:
            return False
        return n >= 1 if not evidence else n >= max(2, 0.05 * len(funcs))
    floor = next(((cls, label) for cls, label in FLOOR if is_floor(cls)), None)
    if floor:
        sample = sorted(f for f, c in unguarded.items() if floor[0] in c)
        verdict = (f"needs {floor[1]}: {floor[0]} in {len(sample)} unguarded of {len(funcs)} functions, "
                   f"e.g. {', '.join(s[:60] for s in sample[:4])}")
    else:
        verdict = "baseline (newer instructions only behind dispatch)" if any(counts.get(c) for c, _ in FLOOR) else "baseline"
    cols = [path.name, f"functions={len(funcs)}"] + [f"{k}={v}" for k, v in counts.items() if v]
    cols += [f"dispatch={','.join(evidence) or 'none'}", f"compiler={'; '.join(compilers) or '?'}"]
    if flags:
        cols.append(f"flags={flags}")
    cols.append(f"verdict={verdict}")
    return "\t".join(cols)


# PostgreSQL's own contrib/PL libraries are noise: only the vector/search/timeseries extensions.
INTEREST = re.compile(r"^(vector|vchord|vectors|vectorscale|pg_search|timescaledb)[\w.-]*\.so$")
for so in sorted(libdir.rglob("*.so")):
    if so.is_symlink() or so.stat().st_size == 0 or not INTEREST.match(so.name):
        continue
    print(fingerprint(so), flush=True)
