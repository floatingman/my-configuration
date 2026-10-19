# vidsummarizer

Installs the [vidsummarizer](https://github.com/floatingman/vidsummarizer)
single-file executable per-user into `~/Documents/vidsummarizer/`.

vidsummarizer (formerly `yt-pipeline`, renamed at 3.0.0) is one portable
executable — a Python zipapp — for the whole local YouTube pipeline:

```
YouTube URL -> yt-dlp (mp3) -> whisper.cpp transcript -> local-LLM summary
```

It is a personal, copy-between-machines tool, so it installs under the
user's `~/Documents` rather than a system-wide path. **The role runs
entirely as the invoking user**: no task uses `become`, and nothing is
written outside `vidsummarizer_install_dir`.

The role lives in the `user_environment` overlay, so it runs on every
profile by default and is skipped with `user_environment: false` (or via
`make configure TAGS=vidsummarizer` to run it alone).

## How it works

1. Ensures `{{ vidsummarizer_install_dir }}` exists (0755, user-owned —
   created by the invoking user, never root).
2. Probes the installed binary with `--version` (read-only, so the probe
   also runs in check mode). Missing/corrupt binary → empty version.
3. Downloads the pinned release **only** when the installed version differs
   from `vidsummarizer_version` (`get_url` with `force: true`, mode 0755);
   reruns are download-free. `force` matters: the version guard is the sole
   "already installed" authority, and get_url's conditional GET would
   otherwise keep a corrupt-but-recently-touched file (server answers
   304 "not modified"). `get_url` stages a temp file in the destination
   directory and moves it into place, so a failed download never truncates
   the binary.
4. Enforces the exec bit (0755) of a present binary — guarded on the
   probe, so it neither fails on a machine without the binary nor fights
   the download's own mode.
5. Smoke-tests `--version` after an install was needed. A binary that will
   not run fails the role; `play.yml`'s block/rescue records it in the
   end-of-run failure report (`make rerun-failed` re-runs it) — same error
   reporting as every other role. No-network and missing-asset failures
   surface the same way instead of aborting silently.

**Check mode (dry run)** never records a false failure on a machine where
the tool is not installed yet: dry runs do not create the install
directory, so when it is missing the download is skipped (the directory
task already reports the would-be change; with the directory present the
dry run still reports the download as a would-be change), and the
exec-bit/verify tasks only touch a binary that is actually present. After
the first real install, dry runs report a plain no-op.

## Version pinning

`vidsummarizer_version` pins the release tag; versions move only through
review, matching the repo's other downloaded binaries (`base.yml` pins +
the bump-versions bot; this role is per-user, so the pin lives in role
defaults and is bumped by hand). To upgrade:

1. Find the latest tag at
   <https://github.com/floatingman/vidsummarizer/releases/latest>.
2. Bump `vidsummarizer_version` in `defaults/main.yml` (bare version, no
   leading `v` — the URL template adds it).
3. Run `make configure TAGS=vidsummarizer` and commit.

Pinning **below 3.0.0** (pre-rename releases) additionally needs
`vidsummarizer_asset_name: yt-pipeline`: the repo URL redirects from the
old `floatingman/yt-pipeline` name, but the release asset filename differs.

Upstream publishes no checksum assets, so the download is not hash-verified
(like the `base.yml` `binaries:` entries); the post-install `--version`
smoke test is the verification.

## Variables

| Variable                     | Default                                              | Purpose                                                       |
| ---------------------------- | ---------------------------------------------------- | ------------------------------------------------------------- |
| `vidsummarizer_version`      | `"3.0.0"`                                            | Pinned release tag (no leading `v`)                           |
| `vidsummarizer_repo`         | `floatingman/vidsummarizer`                          | Upstream repo (`owner/name`)                                  |
| `vidsummarizer_asset_name`   | `vidsummarizer`                                      | Release asset filename (`yt-pipeline` for pre-3.0.0 tags)     |
| `vidsummarizer_release_url`  | GitHub download URL built from the three above        | Full asset URL                                                |
| `vidsummarizer_install_dir`  | `{{ lookup('env','HOME') }}/Documents/vidsummarizer` | Install directory (binary at `<dir>/vidsummarizer`)           |

Machine-specific overrides go in `group_vars/all/local.yml` (commented
examples are in `group_vars/templates/desktop.yml` and
`group_vars/templates/server.yml`).

## Runtime dependencies

The executable itself is self-contained Python (stdlib only, runs on
`python3`), but the *pipeline* shells out to external tools at use time:
`yt-dlp` (audio download), `whisper.cpp` (transcription) and a local LLM
(served via Ollama — installed by the `ai` role when
`ai_local_llm_enabled` is true). This role only installs the executable;
it installs none of those, and none are needed for the install itself.
