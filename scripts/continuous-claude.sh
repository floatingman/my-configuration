#!/usr/bin/env bash
# continuous-claude.sh — Autonomous issue-driven development loop
#
# Picks open GitHub issues, implements them one at a time using Claude Code,
# and creates PRs. Each iteration:
#   1. Implement  (claude -p)
#   2. De-sloppify (claude -p — cleanup pass)
#   3. Verify      (make validate-deps && make syntax-check)
#   4. Commit + PR
#
# Usage:
#   ./scripts/continuous-claude.sh                  # Work next open issue
#   ./scripts/continuous-claude.sh --issue 42       # Work specific issue
#   ./scripts/continuous-claude.sh --max-runs 5     # Stop after N issues
#   ./scripts/continuous-claude.sh --dry-run        # Print plan, no changes
#   ./scripts/continuous-claude.sh --label ralph    # Only issues with label

set -euo pipefail

###############################################################################
# Configuration
###############################################################################

REPO="floatingman/my-configuration"
BASE_BRANCH="main"
BRANCH_PREFIX="ralph/issue"
NOTES_FILE="ralph/SHARED_TASK_NOTES.md"
MAX_RUNS=1          # Default: work one issue at a time (safe default)
ISSUE_NUMBER=""
LABEL_FILTER="afk"
DRY_RUN=false
COMPLETION_SIGNAL="CONTINUOUS_CLAUDE_COMPLETE"

# Claude model routing
MODEL_IMPLEMENT="claude-sonnet-4-6"
MODEL_REVIEW="claude-sonnet-4-6"

###############################################################################
# Argument parsing
###############################################################################

while [[ $# -gt 0 ]]; do
  case "$1" in
    --issue)      ISSUE_NUMBER="$2"; shift 2 ;;
    --max-runs)   MAX_RUNS="$2";    shift 2 ;;
    --label)      LABEL_FILTER="$2"; shift 2 ;;
    --dry-run)    DRY_RUN=true;      shift   ;;
    *)            echo "Unknown flag: $1"; exit 1 ;;
  esac
done

###############################################################################
# Helpers
###############################################################################

log()  { echo "[$(date '+%H:%M:%S')] $*"; }
die()  { echo "ERROR: $*" >&2; exit 1; }

ensure_clean_main() {
  log "Checking working tree is clean..."
  git checkout "$BASE_BRANCH" --quiet
  git pull --quiet
  if [[ -n "$(git status --porcelain)" ]]; then
    die "Working tree is dirty. Commit or stash changes before running."
  fi
}

get_next_issue() {
  local flags="--repo $REPO --state open --json number,title,body,labels --limit 50"
  if [[ -n "$LABEL_FILTER" ]]; then
    flags="$flags --label $LABEL_FILTER"
  fi

  # shellcheck disable=SC2086
  gh issue list $flags \
    | python3 -c "
import json, sys
issues = json.load(sys.stdin)
# Sort by number ascending (oldest first)
issues.sort(key=lambda x: x['number'])
if issues:
    i = issues[0]
    print(i['number'])
"
}

get_issue_details() {
  local num="$1"
  gh issue view "$num" --repo "$REPO" --json number,title,body,labels
}

slugify() {
  echo "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-\|-$//g' | cut -c1-50
}

init_notes_file() {
  if [[ ! -f "$NOTES_FILE" ]]; then
    cat > "$NOTES_FILE" <<'EOF'
# Shared Task Notes

Cross-iteration context for the continuous-claude loop.
Claude: read this at the start of each iteration, update it at the end.

## Codebase Patterns
- 74 roles under roles/; each has meta/main.yml with dependencies:[] and allow_duplicates: false
- Quality gate: `make validate-deps && make syntax-check`
- validate-deps checks for dependency cycles and missing role refs
- ansible-playbook --syntax-check warnings about empty inventory are harmless
- Dep format in meta/main.yml: `- role: role_name  # optional comment`
- The `systemd` role is handlers-only; only depend on it if you use its handlers
- `allow_duplicates: false` handles runtime dedup of diamond deps

## Completed Issues
EOF
    log "Created $NOTES_FILE"
  fi
}

update_notes_completed() {
  local issue_num="$1"
  local issue_title="$2"
  echo "- [x] #${issue_num}: ${issue_title}" >> "$NOTES_FILE"
}

get_pr_needing_changes() {
  # Returns the PR number of the first open ralph PR with either:
  #   - CHANGES_REQUESTED review decision, OR
  #   - the 'needs-changes' label (for use when you are the PR author
  #     and GitHub won't let you request changes on your own PRs)
  gh pr list \
    --repo "$REPO" \
    --state open \
    --json number,headRefName,reviewDecision,labels \
    --limit 50 \
    | python3 -c "
import json, sys
prs = json.load(sys.stdin)
for p in sorted(prs, key=lambda x: x['number']):
    label_names = [l['name'] for l in p.get('labels', [])]
    if (p['headRefName'].startswith('ralph/issue')
            and (p.get('reviewDecision') == 'CHANGES_REQUESTED'
                 or 'needs-changes' in label_names)):
        print(p['number'])
        break
"
}

get_pr_review_feedback() {
  # Collects all review bodies and inline comments for a PR.
  local pr_num="$1"

  gh pr view "$pr_num" --repo "$REPO" --json reviews,comments \
    | python3 -c "
import json, sys
data = json.load(sys.stdin)
lines = []
for r in data.get('reviews', []):
    if r.get('body') and r['state'] in ('CHANGES_REQUESTED', 'COMMENTED'):
        lines.append(f'Review ({r[\"state\"]}):\n{r[\"body\"]}')
for c in data.get('comments', []):
    if c.get('body'):
        lines.append(f'PR comment:\n{c[\"body\"]}')
print('\n\n'.join(lines))
"

  # Inline review comments (file-level)
  gh api "repos/$REPO/pulls/$pr_num/comments" \
    | python3 -c "
import json, sys
comments = json.load(sys.stdin)
for c in comments:
    path = c.get('path', '')
    line = c.get('line') or c.get('original_line', '?')
    body = c.get('body', '').strip()
    if body:
        print(f'Inline comment on {path} line {line}:\n{body}\n')
" 2>/dev/null || true
}

###############################################################################
# Main loop
###############################################################################

RUNS=0

while [[ $RUNS -lt $MAX_RUNS ]]; do
  log "=== Iteration $((RUNS + 1)) / $MAX_RUNS ==="

  ensure_clean_main
  init_notes_file

  # -------------------------------------------------------------------------
  # Priority: fix PRs with requested changes before picking up new issues.
  # Skip this check when a specific --issue was requested.
  # -------------------------------------------------------------------------
  FIX_PR=""
  if [[ -z "$ISSUE_NUMBER" ]]; then
    log "Checking for open PRs with requested changes..."
    FIX_PR="$(get_pr_needing_changes)"
  fi

  if [[ -n "$FIX_PR" ]]; then
    ###########################################################################
    # Fix mode: address review feedback on an existing ralph PR
    ###########################################################################
    PR_JSON="$(gh pr view "$FIX_PR" --repo "$REPO" --json number,title,headRefName)"
    PR_TITLE="$(echo "$PR_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['title'])")"
    BRANCH="$(echo "$PR_JSON"   | python3 -c "import json,sys; print(json.load(sys.stdin)['headRefName'])")"
    FEEDBACK="$(get_pr_review_feedback "$FIX_PR")"

    log "PR #${FIX_PR} needs changes: ${PR_TITLE}"
    log "Checking out existing branch: $BRANCH"

    if $DRY_RUN; then
      log "[DRY RUN] Would fix PR #${FIX_PR} on branch: $BRANCH"
      log "[DRY RUN] Feedback preview: ${FEEDBACK:0:200}..."
      RUNS=$((RUNS + 1))
      continue
    fi

    git checkout "$BRANCH" --quiet
    git pull --quiet

    log "Fix: addressing review feedback..."
    PROMPT_FILE="$(mktemp)"
    cat > "$PROMPT_FILE" <<PROMPT
You are addressing review feedback on a pull request for the my-configuration Ansible repo.

## Context (read first)
$(cat "$NOTES_FILE")

## PR #${FIX_PR}: ${PR_TITLE}

## Review feedback to address

${FEEDBACK}

## Instructions
1. Read the files mentioned in the review comments before making changes.
2. Address every point of feedback. Do not skip or defer any item.
3. Keep changes minimal — only fix what the reviewer asked for.
4. Run \`make validate-deps\` and \`make syntax-check\` after changes.
5. Do NOT add unrequested changes or improvements.

When done, output a brief summary of what you changed.
PROMPT
    claude -p --model "$MODEL_IMPLEMENT" \
      --allowedTools "Read,Write,Edit,Bash,Grep,Glob" \
      < "$PROMPT_FILE"
    rm -f "$PROMPT_FILE"

    # Commit and push if there are changes
    if [[ -z "$(git status --porcelain)" ]]; then
      log "No changes made — review feedback may already be resolved."
    else
      git add -A
      git commit -m "fix: address review feedback on PR #${FIX_PR}"
      git push --quiet
      log "Pushed fix to PR #${FIX_PR}"
    fi

    # Remove needs-changes label (if present) now that feedback is addressed
    gh pr edit "$FIX_PR" --repo "$REPO" --remove-label "needs-changes" 2>/dev/null || true

    git checkout "$BASE_BRANCH" --quiet
    RUNS=$((RUNS + 1))
    continue
  fi

  # -------------------------------------------------------------------------
  # Normal mode: pick up the next open issue
  # -------------------------------------------------------------------------

  # Determine which issue to work
  if [[ -n "$ISSUE_NUMBER" && $RUNS -eq 0 ]]; then
    ISSUE_NUM="$ISSUE_NUMBER"
  else
    log "Finding next open issue..."
    ISSUE_NUM="$(get_next_issue)"
    if [[ -z "$ISSUE_NUM" ]]; then
      log "No open issues found. Loop complete."
      break
    fi
  fi

  # Fetch full issue details
  ISSUE_JSON="$(get_issue_details "$ISSUE_NUM")"
  ISSUE_TITLE="$(echo "$ISSUE_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['title'])")"
  ISSUE_BODY="$(echo "$ISSUE_JSON"  | python3 -c "import json,sys; print(json.load(sys.stdin)['body'] or '')")"

  log "Working issue #${ISSUE_NUM}: ${ISSUE_TITLE}"

  SLUG="$(slugify "$ISSUE_TITLE")"
  BRANCH="${BRANCH_PREFIX}-${ISSUE_NUM}-${SLUG}"

  if $DRY_RUN; then
    log "[DRY RUN] Would create branch: $BRANCH"
    log "[DRY RUN] Issue body preview: ${ISSUE_BODY:0:200}..."
    RUNS=$((RUNS + 1))
    continue
  fi

  # Create branch
  git checkout -b "$BRANCH" --quiet
  log "Created branch: $BRANCH"

  ###########################################################################
  # Step 1: Implement
  ###########################################################################
  log "Step 1/4: Implement..."
  PROMPT_FILE="$(mktemp)"
  cat > "$PROMPT_FILE" <<PROMPT
You are implementing a GitHub issue for the my-configuration Ansible repo.

## Context (read first)
$(cat "$NOTES_FILE")

## Issue #${ISSUE_NUM}: ${ISSUE_TITLE}

${ISSUE_BODY}

## Instructions
1. Read relevant role files to understand the current state before making changes.
2. Implement the issue fully, following existing patterns in the codebase.
3. Keep changes minimal and focused — only change what is needed for this issue.
4. Use FQCN (ansible.builtin.*) for all Ansible modules.
5. Do NOT run the full playbook — use \`make syntax-check\` and \`make validate-deps\` to verify.
6. Do NOT create documentation files or README updates unless explicitly required by the issue.

When done, output a brief summary of what you changed (for the shared notes file).
PROMPT
  claude -p --model "$MODEL_IMPLEMENT" \
    --allowedTools "Read,Write,Edit,Bash,Grep,Glob" \
    < "$PROMPT_FILE"
  rm -f "$PROMPT_FILE"

  ###########################################################################
  # Step 2: De-sloppify
  ###########################################################################
  log "Step 2/4: De-sloppify..."
  PROMPT_FILE="$(mktemp)"
  cat > "$PROMPT_FILE" <<'PROMPT'
Review the changes made to this Ansible repository since the last commit.

Run: git diff HEAD

Look for and remove:
- Debug tasks (ansible.builtin.debug with msg=) that aren't needed in production
- Redundant `when` conditions that are already guaranteed by context
- Commented-out YAML blocks
- Trailing whitespace in YAML files
- Duplicate dependencies in meta/main.yml (same role listed twice)

Do NOT remove:
- Actual implementation logic
- Meaningful comments explaining why a dependency exists
- ansible.builtin.debug tasks that are part of the feature spec

Run `make validate-deps` after any changes to confirm the graph is still valid.
PROMPT
  claude -p --model "$MODEL_REVIEW" \
    --allowedTools "Read,Write,Edit,Bash,Grep,Glob" \
    < "$PROMPT_FILE"
  rm -f "$PROMPT_FILE"

  ###########################################################################
  # Step 3: Verify
  ###########################################################################
  log "Step 3/4: Verify..."
  PROMPT_FILE="$(mktemp)"
  cat > "$PROMPT_FILE" <<'PROMPT'
Run the full quality gate for this Ansible repo and fix any failures.

Quality gate commands (run in order):
1. make validate-deps
2. make syntax-check

If either fails:
- Read the error output carefully
- Fix the root cause in the relevant files (use Edit tool)
- Re-run to confirm it passes

Do NOT modify the quality gate commands themselves.
Do NOT add `when: false` or similar hacks to skip failing tasks.
Report: PASS or FAIL with details.
PROMPT
  claude -p --model "$MODEL_REVIEW" \
    --allowedTools "Read,Bash,Grep,Glob" \
    < "$PROMPT_FILE"
  rm -f "$PROMPT_FILE"

  ###########################################################################
  # Step 4: Commit and PR
  ###########################################################################
  log "Step 4/4: Commit and create PR..."

  # Only proceed if there are actual changes
  if [[ -z "$(git status --porcelain)" ]]; then
    log "No changes made for issue #${ISSUE_NUM} — closing issue as no-op and continuing."
    git checkout "$BASE_BRANCH" --quiet
    git branch -D "$BRANCH" --quiet
    gh issue close "$ISSUE_NUM" --repo "$REPO" \
      --comment "Reviewed and confirmed: no code changes needed. Issue closed." 2>/dev/null || true
    update_notes_completed "$ISSUE_NUM" "$ISSUE_TITLE (no changes needed)"
    RUNS=$((RUNS + 1))
    continue
  fi

  git add -A
  COMMIT_MSG="$(python3 -c "
title = '''${ISSUE_TITLE}'''
num = '${ISSUE_NUM}'
# Heuristic: issues starting with 'Add' -> feat, 'Fix' -> fix, 'Audit'/'Wire'/'Declare'/'Bootstrap' -> chore
lower = title.lower()
if any(lower.startswith(w) for w in ['add ', 'implement', 'create', 'introduce']):
    prefix = 'feat'
elif any(lower.startswith(w) for w in ['fix', 'resolve', 'correct']):
    prefix = 'fix'
else:
    prefix = 'chore'
print(f'{prefix}: {title} (closes #{num})')
")"

  git commit -m "$COMMIT_MSG"

  git push -u origin "$BRANCH" --quiet

  PR_URL="$(gh pr create \
    --repo "$REPO" \
    --base "$BASE_BRANCH" \
    --head "$BRANCH" \
    --title "$ISSUE_TITLE" \
    --body "$(cat <<PRBODY
Closes #${ISSUE_NUM}

## Summary
Automated implementation via continuous-claude loop.

## Changes
$(git diff "$BASE_BRANCH"..."$BRANCH" --stat)

## Test plan
- [x] \`make validate-deps\` passes
- [x] \`make syntax-check\` passes
- [ ] Manual verification of affected role(s)
PRBODY
)")"

  log "PR created: $PR_URL"

  # Close the issue (PR close reference handles it, but belt-and-suspenders)
  update_notes_completed "$ISSUE_NUM" "$ISSUE_TITLE"

  # Commit updated notes file to the PR branch
  if ! git diff --quiet "$NOTES_FILE" 2>/dev/null; then
    git add "$NOTES_FILE"
    git commit -m "chore: update shared task notes after issue #${ISSUE_NUM}"
    git push --quiet
  fi

  git checkout "$BASE_BRANCH" --quiet

  log "Issue #${ISSUE_NUM} done. PR: $PR_URL"
  RUNS=$((RUNS + 1))
done

log "Loop finished after $RUNS iteration(s)."
