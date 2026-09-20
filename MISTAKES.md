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
