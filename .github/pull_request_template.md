## What changes

## How it was checked
- [ ] `bash -n scripts/*.sh` and `python3 -m py_compile scripts/*.py`
- [ ] `action test` workflow green (official image passes, Bitnami is caught)
- [ ] For a new suite or image: one `audit` run with the filter set to it, report attached
