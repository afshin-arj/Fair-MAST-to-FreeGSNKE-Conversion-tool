---
name: ship-to-main
description: >-
  Git release gate for Fair-MAST→FreeGSNKE: after tests and smoke are green,
  create a feature branch, commit, push, and land changes on GitHub main via PR
  merge (preferred) or explicit fast-forward push. Never force-push. Use when
  shipping, releasing, pushing to main, or when mast-freegsnke-super reaches
  the git phase.
---

# Ship to main

## Preconditions (all required)

- [ ] `pytest -q` passed (or documented subset + reason)
- [ ] No secrets in diff (`.env`, credentials, tokens)
- [ ] No `data_cache/` / large Zarr / run artifacts unless user explicitly asked
- [ ] Diff matches the intended feature (shot-only / authority hardening)

If any fail → **do not commit or push**.

## Git sequence

Run status/diff/log **in parallel** first:

```bash
git status -sb
git diff
git diff --staged
git log -8 --oneline
git remote -v
git branch -vv
```

### 1) Sync + branch

```bash
git fetch origin
git checkout main
git pull --ff-only origin main
git checkout -b feat/<short-topic>
```

If `main` does not exist locally, use the repo’s default branch (`master` only if that is actually default).

### 2) Stage + commit

```bash
git add AGENTS.md .cursor src tests configs templates pyproject.toml README.md CHANGELOG.md
# adjust paths to what actually changed; review `git status` before commit
```

Commit message via HEREDOC (PowerShell-safe alternative if needed):

```bash
git commit -m "$(cat <<'EOF'
feat: enable shot-only Fair-MAST to FreeGSNKE happy path

Make download-to-execution automatic from shipped defaults so users only supply a shot number.
EOF
)"
```

On Windows PowerShell without bash HEREDOC:

```powershell
git commit -m "feat: enable shot-only Fair-MAST to FreeGSNKE happy path`n`nMake download-to-execution automatic from shipped defaults so users only supply a shot number."
```

Never `--no-verify` unless the user explicitly requests it.

### 3) Land on GitHub `main`

**Preferred:**

```bash
git push -u origin HEAD
gh pr create --base main --title "feat: shot-only automation" --body "$(cat <<'EOF'
## Summary
- Shot-only happy path / authority hardening (describe actual changes)

## Test plan
- [x] pytest -q
- [ ] mast-freegsnke doctor --config configs/default.json
- [ ] mast-freegsnke run --shot <N> (if env available)
EOF
)"
gh pr merge --merge
```

**Direct push to `main`** when the user demands shipping to main (this project: after green pytest on a finished fix/feature, **always** land on `main` without waiting for a second ask):

```bash
git checkout main
git merge --ff-only feat/<short-topic>
git push origin main
```

If non-ff → stop; use PR. **Never** `--force` / `--force-with-lease` on `main`.

### 4) Verify

```bash
git status -sb
gh pr view --web   # if PR used
```

## Report

Return: branch name, commit SHA, PR URL or `main` push result, and remaining env blockers (s5cmd / FreeGSNKE / real machine_authority).
