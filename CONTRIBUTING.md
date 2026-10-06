# Contributing

Thanks for helping make PostgreSQL images run on more CPUs.

## Ask for an image to be audited
Open a [Check an image](../../issues/new?template=audit-an-image.yml) issue with the image, tag and architectures.

## Report a wrong result
Open a [Crash or wrong result](../../issues/new?template=crash-report.yml) issue with your CPU (`grep -m1 "model name" /proc/cpuinfo`), the image digest and the server log around `signal 4`.

## Change the code
- Scripts: `scripts/inner.sh` (runs inside the image), `scripts/probe.sh` (host side), `scripts/corelibs.py` and `scripts/explain.sh` (crash analysis), `scripts/fingerprint.py` (static scan), `scripts/report.py`.
- Before a pull request: `bash -n scripts/*.sh` and `python3 -m py_compile scripts/*.py`.
- A new suite or image: run the `audit` workflow with its filter set to that image and attach the job summary.
- The `action test` workflow must stay green: the official pgvector image passes, Bitnami's is caught.

Keep claims in the README backed by a run: link the workflow run that shows them.
