# Security policy

This repository runs container images it does not control inside GitHub Actions runners, with a QEMU binary layered
on top. If you find a way for a tested image or a crafted core file to affect the runner beyond its own job, or a
flaw in `scripts/corelibs.py` when it parses untrusted cores, please report it privately through
[GitHub security advisories](../../security/advisories/new) rather than an issue.

A CPU-compatibility problem in someone else's image (an "Illegal instruction" crash) is not a security issue of this
repository; report it to that image's maintainers, and feel free to open a normal issue here so it can be audited.
