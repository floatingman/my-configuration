# MISTAKES.md

Review relevant entries before planning or editing code.
Add an entry after a confirmed mistake or user correction.
Keep entries short, specific, and project-related.
Merge repeated mistakes instead of creating duplicates.
Do not record transient tool failures or unverified guesses.

## Entry format

### [YYYY-MM-DD] [Short title]

**Mistake:** [What the agent did wrong]
**Root cause:** [Why the decision failed]
**Prevention:** [The rule to apply next time]
**Verification:** [How to confirm the mistake was avoided]

### [2026-09-06] Role-default dicts are replaced, not merged

**Mistake:** Put an optional key (`idle_timeout`) inside a role's
`defaults/main.yml` dict (`network_shares_config`) and referenced it from a
template, assuming defaults fill missing keys when `group_vars` overrides
the dict.
**Root cause:** Ansible variable precedence replaces the whole variable —
hash merging is off by default — so a `group_vars` dict with only some keys
hides the role-default siblings entirely.
**Prevention:** Keep optional scalars as separate flat prefixed variables
(`network_shares_idle_timeout`); reserve `<role>_config` dicts for keys a
host always sets together. If a dict must self-merge, do it with an explicit
`set_fact` + `combine()` before first use.
**Verification:** `make configure TAGS=<role>` renders templates without
"object of type 'dict' has no attribute" errors.

### [2026-10-19] get_url conditional GET keeps corrupt destination files

**Mistake:** The vidsummarizer role guarded its download with a version
probe but let `get_url` run without `force`; verification showed a
corrupted destination binary surviving the run (task reported ok).
**Root cause:** Without `checksum`/`force`, `get_url` sends a conditional
GET using the destination's mtime; a corrupt file written seconds earlier
is "newer" than the release asset, the server answers 304, and get_url
reports the file present without checking content.
**Prevention:** When a separate guard (version probe, stat check) is the
sole "already installed" authority, set `force: true` on the guarded
`get_url` so every guarded run performs a guaranteed full download. Keep
the guard itself responsible for idempotency.
**Verification:** Corrupt the installed binary, rerun the role: the
binary is replaced and `--version` succeeds; a clean rerun still skips
the download entirely.

### [2026-10-14] Recursive mode "2775" put setgid on Rust toolchain files

**Mistake:** The rust role set `mode: "2775"` with `recurse: true` on
`/opt/rust`, assuming the mode would only affect directories.
**Root cause:** `ansible.builtin.file` applies `mode` literally to every file
and directory when recursing. setgid on executables makes the kernel set
`AT_SECURE` at exec (egid `devtools` != rgid), so glibc refuses to expand
`$ORIGIN` in rustc's RUNPATH — every `cargo build`/`rustc` invocation fails
with `librustc_driver-*.so: cannot open shared object file` even though the
library exists (`ldd` misleadingly resolves it, because it never execs the
binary).
**Prevention:** Never recurse a mode containing setuid/setgid bits over a
tree with executables. Recurse ownership only; apply `2775` to directories
explicitly (`find` + `file` loop). File creation/replacement by group
members still works through the group-writable directories. The role also
carries an idempotent repair pass that strips setuid/setgid from regular
files, so rerunning the playbook heals hosts broken by the old mode.
**Verification:** `rustc --version` works as a non-root user after the role
runs; `find /opt/rust -type f -perm /6000` returns nothing; `find /opt/rust
-type d -perm /2000` still lists the directories.
