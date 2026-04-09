---
name: social-poster
description: "Deploy olav blog and post to social media platforms using browser automation. Use when content is ready in olav-post/archive/ and the user says 'post to social', 'social push', 'publish post', 'post update', '发帖', '推送更新', or 'push this to social'. Reads draft content from olav-post/archive/YYYY-MM-DD/. Requires content-writer to have been run first."
argument-hint: "Platform(s) to post to: all | linkedin | hackernews | reddit | zhihu | juejin | wechat-mp. Default: all."
---

# Social Poster Skill

Deploy the olav blog update and post platform drafts from `olav-post/archive/` via Chrome DevTools MCP.

## Scope

This skill **only deploys and posts**. It does NOT write content.
Content must be ready in `olav-post/archive/YYYY-MM-DD/` — run `content-writer` first if it isn't.

## Browser Tool

This skill uses **Chrome DevTools MCP** (`mcp_chrome-devtoo_*`).
The user must have Chrome running with remote debugging enabled:

```bash
# Linux/macOS
google-chrome --remote-debugging-port=9222 &

# Windows
start chrome --remote-debugging-port=9222
```

Fallback: if Chrome DevTools MCP is unavailable, use Playwright MCP (`mcp_playwright_browser_*`) — most interaction patterns are the same; substitute `mcp_playwright_browser_navigate` for `mcp_chrome-devtoo_navigate_page`, etc.

---

## Step-by-Step Procedure

### Step 0 — Load Archive

Find the most recent `olav-post/archive/YYYY-MM-DD/` directory:

```bash
ls -d /home/yhvh/Olav/olav-post/archive/*/  | sort | tail -1
```

Read `_meta.md` from that directory. Extract:
- **Blog Slug** (e.g., `olav-v010-launch`)
- **Blog URL EN** (e.g., `https://olavai.com/blog/olav-v010-launch`)
- **Blog URL ZH** (e.g., `https://olavai.com/zh/blog/olav-v010-launch`)
- Which platform files exist (check which of `linkedin.md`, `hackernews.md`, `reddit.md`, `zhihu.md`, `juejin.md`, `wechat-mp.md` are present)

If `_meta.md` doesn't exist or the archive is empty, stop and ask user to run `content-writer` first.

### Step 1 — Deploy Blog

Read and follow: [blog-deploy.md](./references/blog-deploy.md)

Do NOT proceed to Step 2 until:
1. `npm run worker:deploy` completes without error
2. Blog live URL is visually confirmed correct via browser MCP

If deploy fails, stop and report the error. Do not post to any platform with a broken blog URL.

### Step 2 — Post to Each Platform

For each platform with a draft file in the archive, follow the platform workflow in order:

| Priority | File | Platform | Workflow |
|---|---|---|---|
| 1 | `hackernews.md` | HackerNews | [hackernews.md](./references/hackernews.md) |
| 2 | `linkedin.md` | LinkedIn | [linkedin.md](./references/linkedin.md) |
| 3 | `reddit.md` | Reddit | [reddit.md](./references/reddit.md) |
| 4 | `zhihu.md` | 知乎 | [zhihu.md](./references/zhihu.md) |
| 5 | `juejin.md` | 掘金 | [juejin.md](./references/juejin.md) |
| 6 | `wechat-mp.md` | 微信公众号 | [wechat-mp.md](./references/wechat-mp.md) |

**Per platform:**
1. Read the platform draft from `olav-post/archive/YYYY-MM-DD/<platform>.md`
2. Follow the browser workflow in the reference file above
3. Take screenshot confirming draft/form state
4. Report to user before moving to next platform

**Critical rules:**
- Save drafts only — never click Publish/Post/群发
- If login is required, pause and ask user to log in manually, then resume
- If a platform fails, report the error and move to the next one — do not abort everything

### Step 3 — Update _meta.md

After all platforms are complete, update `olav-post/archive/YYYY-MM-DD/_meta.md`:

```markdown
## Posting Status
- [x] Blog deployed — YYYY-MM-DD HH:MM UTC
- [x] HackerNews — draft saved / form ready
- [x] LinkedIn — draft saved
- [x] Reddit — draft saved in r/X
- [x] 知乎 — draft saved
- [x] 掘金 — draft auto-saved
- [x] 微信公众号 — draft saved
```

### Step 4 — Summary Report

Output a final table:

```
Blog deployed:  https://olavai.com/blog/<slug>
Archive:        olav-post/archive/YYYY-MM-DD/

Platform        Status     Notes
──────────────────────────────────────────────────
HackerNews      ✅ ready   Form filled, awaiting manual submit
LinkedIn        ✅ draft   Draft saved, awaiting manual publish
Reddit          ✅ draft   r/selfhosted draft, awaiting manual submit
知乎             ✅ draft   草稿已保存，请审查后手动发布
掘金             ✅ draft   草稿自动保存，请审查后手动发布
微信公众号        ✅ draft   草稿已保存，请审查后手动群发
```

Include screenshots for any platforms where something was unexpected.

---

## If Only Specific Platforms Were Requested

If user specified specific platforms (e.g., "post to LinkedIn and HackerNews only"):
- Skip Step 1 (deploy blog) only if blog is already live — verify first
- Run only the requested platform workflows in Step 2
- Update `_meta.md` for the completed platforms only
