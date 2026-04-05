# OLAV Repository Architecture & Push Rules

## ⚠️ CRITICAL: Repository Address Mapping

This workspace uses a **monorepo split** with distinct repository targets. **ALWAYS verify the correct remote before pushing.**

### Authorized Repositories

| Repo Name | GitHub URL | Git Remote | Purpose | Push Branch | Status |
|-----------|-----------|-----------|---------|-------------|--------|
| **olav-docs** | `https://github.com/james-olavai/olav-docs.git` | `origin` (in `olav-doc/`) | **Documentation only** — MkDocs config, docs content, i18n | `main` | ✅ **ACTIVE** |
| **olav** (main) | `http://192.168.100.50:3000/admin/olav.git` | `gitea` | **Main platform core** — src/olav, pyproject.toml, CLI | `main`, `0.10.0`, feature branches | ✅ **ACTIVE** |
| olav (mirror) | `https://github.com/yhvh-chen/Olav.git` | `origin` (in root) | GitHub backup/mirror | Synced with gitea | ⚠️ **Backup only** |
| ~~olav-jamesai~~ | `https://github.com/james-olavai/olav.git` | `james` | ❌ **DEPRECATED** — Do NOT push here | — | 🗑️ **DELETE** |

### Directory Mappings

```
/home/yhvh/Olav/
├── olav-doc/                    ← SEPARATE GIT REPO
│   ├── .git/ → origin = olav-docs.git (james-olavai)
│   ├── mkdocs.yml               → Deploy to https://docs.olavai.com
│   ├── docs/
│   │   ├── getting-started/
│   │   ├── guides/
│   │   ├── concepts/
│   │   └── reference/
│   └── Push rules: ALWAYS push to olav-docs.git, NEVER to main olav repo
│
├── olav-web/                    ← SUBMODULE/SUBDIR (monorepo child)
│   ├── package.json
│   ├── wrangler.toml           → Cloudflare Workers
│   ├── astro.config.mjs        → Astro SSG config
│   └── worker/src/index.ts     → Worker entrypoint
│   └── NOT a separate git repo — deployed via Cloudflare Pages
│
├── olav-netops/                 ← SUBMODULE/SUBDIR (monorepo child)
├── olav-ent/                    ← SUBMODULE/SUBDIR (monorepo child)
│
├── src/olav/                    ← PLATFORM CORE
│   ├── cli/
│   ├── core/
│   ├── platform/
│   ├── agents/
│   └── ... (source tree)
│
├── pyproject.toml               ← Python package config
├── .pypirc                      ← PyPI credentials (NEVER commit)
├── .git/ → remotes:
│   ├── gitea = http://192.168.100.50:3000/admin/olav.git (PRIMARY)
│   ├── origin = https://github.com/yhvh-chen/Olav.git (BACKUP)
│   └── james = https://github.com/james-olavai/olav.git (DEPRECATED)
│
└── .github/
    └── copilot-instructions.md (this file)
```

---

## Push Workflow Rules

### ✅ ALLOWED Operations

**For olav-doc/ (Documentation):**
```bash
cd olav-doc
git add <files>
git commit -m "message"
git push origin main     # ✅ CORRECT: pushes to james-olavai/olav-docs.git
```

**For src/olav (Platform core):**
```bash
cd /home/yhvh/Olav
git add src/olav pyproject.toml
git commit -m "message"
git push gitea 0.10.0    # ✅ PRIMARY: gitea (Gitea server)
git push origin 0.10.0   # ✅ BACKUP: GitHub mirror
```

**For PyPI Release:**
```bash
cd /home/yhvh/Olav
uv build
uvx twine upload --config-file .pypirc -r pypi dist/*  # ✅ CORRECT: uses [pypi] token
```

**For Cloudflare Pages (olav-web):**
- olav-web is NOT a separate git repo
- Cloudflare Pages auto-deploys from main olav repo
- Configure in Cloudflare Dashboard: Root directory = `olav-web`

---

## ❌ FORBIDDEN Operations

| Operation | Why | Fix |
|-----------|-----|-----|
| `git push james 0.10.0` | james remote is DEPRECATED | Delete the remote: `git remote rm james` |
| `git commit` in `olav-web/` individually | olav-web belongs to main repo monorepo | Commit from repo root with `src/`, `olav-web/`, etc. together |
| Push olav-doc to main repo | docs ≠ platform core | Use separate `.git` in olav-doc/ only |
| Push olav-web individually | Web is subdir, not submodule | No separate .git in olav-web/ |
| Commit .pypirc to git | Credentials exposure | Always `.gitignore` — use local file only |
| Use `push -u origin` without checking | Will push to wrong branch/remote | Always specify: `git push gitea` or `git push origin` explicitly |

---

## Disaster Recovery Checklist

If you accidentally pushed to wrong remote:

**Scenario: Pushed to james-olavai/olav by mistake**
1. ❌ Branch exists on james remote
2. ✅ Local reset: `git reset --hard gitea/0.10.0` (back to Gitea primary)
3. ⚠️ Manual cleanup: Delete branch on GitHub (Settings → Branches → Delete)
4. Use `git push gitea` for all future pushes on this project

**Scenario: Pushed documentation to main olav repo**
1. ✅ Keep documentation in olav-doc/ repo only
2. ❌ Do NOT mix docs commits into main olav commits
3. ✅ Revert unwanted commits from main repo if needed

**Scenario: Can't delete james-olavai/olav repo**
1. ✅ Use GitHub CLI with delete_repo scope: `gh auth refresh -s delete_repo`
2. ✅ Or manual delete via Web UI: https://github.com/james-olavai/olav/settings
3. ⚠️ Requires Admin permissions on the organization

---

## Branch/Release Strategy

| Branch | Repo | Release Target | Status |
|--------|------|---|--------|
| `main` | gitea (primary) | dev/staging | 🔄 Active development |
| `0.10.0` | gitea (primary) | PyPI (olav 0.10.0) | ✅ Released |
| feature/* | gitea (primary) | development only | 🔄 Feature branches |

---

## Environment Variables / Secrets

| File | Location | Git Tracking | Purpose |
|------|----------|---|---------|
| `.pypirc` | `/home/yhvh/Olav/.pypirc` | ❌ IGNORED (git) | PyPI auth token — LOCAL ONLY |
| `wrangler.toml` | `/home/yhvh/Olav/olav-web/wrangler.toml` | ✅ Tracked | Cloudflare Workers config |
| `.env` (if any) | N/A | ❌ IGNORED | Never commit secrets |

---

## Agent Guardrails

**BEFORE ANY GIT PUSH, VERIFY:**
1. ✅ Current directory: `pwd` → `/home/yhvh/Olav` or `/home/yhvh/Olav/olav-doc/`?
2. ✅ Current branch: `git branch` → Which branch?
3. ✅ Remote target: `git remote -v` → Which remote am I pushing to?
4. ✅ Commit content: `git diff --cached --stat` → What am I committing?

**Command Pattern:**
```bash
git status                    # Always check first
git remote -v | grep -E '(gitea|origin|james)'  # Confirm remotes
git push <EXPLICIT_REMOTE> <EXPLICIT_BRANCH>    # Never use implicit defaults
```

**Forbidden shorthand:**
- ❌ `git push` (uses default, unclear)
- ❌ `git push -u origin` (auto-sets upstream, risky)
- ✅ `git push gitea main` (explicit, unambiguous)
- ✅ `git push origin 0.10.0` (explicit, unambiguous)

---

## Summary

| Goal | Correct Command | Common Mistake |
|------|---------|---|
| Push docs | `cd olav-doc && git push origin main` | `git push` from root (wrong repo) |
| Push code | `git push gitea 0.10.0` | `git push james 0.10.0` (deprecated remote) |
| Release to PyPI | `uvx twine upload -r pypi` | Wrong token in [testpypi] section |
| Deploy Web | Cloudflare auto-deploy from root repo, no manual git push | Trying to push olav-web as separate repo |

**Golden rule:** When in doubt, **explicitly specify both remote AND branch**.

