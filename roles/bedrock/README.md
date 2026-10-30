# bedrock

Claude access through company AWS Bedrock: installs the [SUSE bedrock-toolkit](https://github.com/SUSE/bedrock-toolkit) `bedrock` CLI per-user and wires the AWS SSO profile it needs.

## What it does

1. Installs `bedrock` into `~/.local/bin` (checksum-verified GitHub release, pinned version, user-owned so self-replacement keeps working).
2. Asserts AWS CLI v2 is on PATH (installed repo-wide via the `asdf` role from `group_vars/all/base.yml`; this role never installs it).
3. Writes the SSO profile into `~/.aws/config` as a marked `blockinfile` (never templates the whole file; other profiles are untouched). A profile written manually is detected and adopted.
4. Probes the SSO session (`aws sts get-caller-identity`) and runs `bedrock setup` only when it is valid, with the full flag set. Re-running setup with different options repoints the profile at a nonexistent role, so the command is always the complete flag set.

## Required variables (company-private)

These are `null` in `roles/bedrock/defaults/main.yml` because the repo is public. Real values go ONLY in the gitignored `group_vars/all/local.yml`:

| Variable | What it is (generic) |
| --- | --- |
| `bedrock_sso_start_url` | The SSO start URL from the onboarding docs (`https://<directory-id>.awsapps.com/start`) |
| `bedrock_sso_account_id` | The account ID to pick in the `aws configure sso` account picker |
| `bedrock_sso_role_name` | The permission-set name to pick in the `aws configure sso` role picker |
| `bedrock_setup_id` | The `--id` value from the `bedrock setup` command your admin sent |

Optional overrides (tracked defaults): `bedrock_version`, `bedrock_install_dir`, `bedrock_sso_profile_name` (default `my-sso`), `bedrock_sso_region` (default `eu-central-1`), `bedrock_region` (default `us-east-1`), `bedrock_setup_force`.

## Daily flow

```bash
aws sso login --profile my-sso   # browser sign-in; manual by design
make configure TAGS=bedrock      # applies config, runs `bedrock setup` when the session is valid
```

Without a valid session the playbook run still succeeds and prints the exact `aws sso login` step instead of failing (headless machines included: `aws sso login` has a URL + code fallback for any browser). On headless machines run `aws sso login` on a machine with a browser and copy the session, or use the printed URL/code flow.

## What is NOT automated (by design)

- **Browser SSO sign-in**: `aws sso login` requires interactive browser authentication against the company IdP.
- **Choosing the account/permission set**: per-user values, entered in `group_vars/all/local.yml`.
- **`bedrock claude`**: only prints Claude Code settings; you copy its output into your own configuration yourself.

## Optional: point pi and omp at Bedrock

Opt-in via `group_vars/all/local.yml` (defaults `false`, since this changes which backend and budget every session uses):

```yaml
bedrock_pi_enabled: true     # ~/.pi/agent/settings.json defaultProvider/defaultModel
bedrock_omp_enabled: true    # omp modelRoles.default via `omp config set`
bedrock_claude_model: "us.anthropic.claude-sonnet-5-5"   # must keep the us.* inference-profile prefix
```

Both agents read AWS credentials from the environment, not from these settings. Since exporting `AWS_PROFILE` globally redirects every `aws` command, launch them through a wrapper instead:

```bash
alias omp-work='AWS_PROFILE=bedrock AWS_REGION=us-east-1 omp'
alias pi-work='AWS_PROFILE=bedrock AWS_REGION=us-east-1 pi'
```

Caveats:

- **pi + chezmoi**: if your pi-dotfiles template manages `~/.pi/agent/settings.json`, chezmoi wins on the next apply. Prefer editing the template there, or re-run `make configure TAGS=bedrock` after `chezmoi apply`.
- **omp one-shots**: `omp -p` runs your hook extensions after the main reply (each pays Bedrock latency); interactive use is the intended mode.

## Upgrading

Bump `bedrock_version` in `roles/bedrock/defaults/main.yml`; the role downloads the new release on the next run (the version probe skips the download while the installed version matches).
