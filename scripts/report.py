#!/usr/bin/env python3
"""Turns the per-job probe outputs into one markdown report.
Usage: scripts/report.py RESULTS_DIR > report.md"""
import json
import pathlib
import sys

CPUS = {
    "amd64": ["native", "Nehalem", "SandyBridge", "IvyBridge", "Haswell"],
    "arm64": ["native", "cortex-a53", "cortex-a72", "neoverse-n1"],
}
ICON = {"PASS": "✅", "FAIL": "❌", "N/A": "➖", "SKIP": "·"}


def read_tsv(path):
    if not path.exists():
        return []
    return [line.split("\t") for line in path.read_text(errors="replace").splitlines() if line.strip()]


root = pathlib.Path(sys.argv[1])
jobs = []
for d in sorted(root.iterdir()):
    meta_file = d / "meta.json"
    if not meta_file.exists():
        continue
    meta = json.loads(meta_file.read_text())
    meta["results"] = read_tsv(d / "results.tsv")
    meta["info"] = {r[0]: r[1] if len(r) > 1 else "" for r in read_tsv(d / "info.tsv")}
    meta["fingerprint"] = read_tsv(d / "fingerprint.tsv")
    meta["explain"] = {(r[0], r[1]): r[2:] for r in read_tsv(d / "explain.tsv") if len(r) >= 3}
    jobs.append(meta)

print("# Vector Postgres images on older CPUs\n")
print("Each suite starts the real PostgreSQL server natively, then on emulated CPU models (QEMU user mode).")
print("amd64: Nehalem = SSE4.2, no AVX · SandyBridge = AVX · IvyBridge = AVX + F16C · Haswell = AVX2 + FMA, no AVX-512.")
print("arm64: cortex-a53/a72 = ARMv8.0 (Raspberry Pi 3/4) · neoverse-n1 = ARMv8.2 + FP16 (Graviton2, Ampere Altra);")
print("arm64 native = QEMU's `max` CPU, the host is amd64. ➖ = suite fails natively too (test problem, not a CPU problem).\n")

failures = []
for arch in ("amd64", "arm64"):
    arch_jobs = [j for j in jobs if j["arch"] == arch]
    if not arch_jobs:
        continue
    cols = CPUS[arch]
    print(f"## {arch}\n")
    print("| image | suite | " + " | ".join(cols) + " |")
    print("|---|---|" + "---|" * len(cols))
    for j in sorted(arch_jobs, key=lambda j: j["name"]):
        rows = {}
        for r in j["results"]:
            r += [""] * (4 - len(r))
            suite, cpu, status, detail = r[:4]
            rows.setdefault(suite, {})[cpu] = (status, detail)
            if status == "FAIL":
                failures.append((j["name"], arch, suite, cpu, detail, j["explain"].get((suite, cpu))))
        if not rows:
            print(f"| {j['name']} | (no output) |" + " |" * len(cols))
            continue
        for suite, cells in rows.items():
            if suite == "-":
                status, detail = next(iter(cells.values()))
                print(f"| {j['name']} | {status}: {detail[:80]} |" + " |" * len(cols))
                continue
            line = [ICON.get(cells.get(c, ("",))[0], "") for c in cols]
            print(f"| {j['name']} | {suite} | " + " | ".join(line) + " |")
    print()

print("## Failures\n")
if not failures:
    print("None.\n")
for name, arch, suite, cpu, detail, why in failures:
    line = f"- **{name}** ({arch}) `{suite}` on **{cpu}**: {detail}"
    if why:
        line += f"\n  - faulting instruction: `{why[0]}` in {why[1] if len(why) > 1 else '?'}"
    print(line)
print()

print("## Static fingerprint of the extension libraries\n")
print("Per library: functions that use each instruction class, CPU-dispatch evidence, compiler, verdict.")
print("Code behind a runtime CPU check is safe; the dynamic table decides.\n")
for j in sorted(jobs, key=lambda j: (j["name"], j["arch"])):
    for r in j["fingerprint"]:
        print(f"- **{j['name']}** ({j['arch']}) " + " · ".join(r))
print()

print("## Images and hosts\n")
for j in sorted(jobs, key=lambda j: (j["name"], j["arch"])):
    i = j["info"]
    print(f"- **{j['name']}** ({j['arch']}): `{i.get('digest', '?')}` · {i.get('version', '?')} · "
          f"extensions: {i.get('extensions', '?')} · host: {i.get('host_cpu', '?')} [{i.get('host_flags', '').strip()}]")
