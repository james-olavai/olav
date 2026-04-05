# Cloudflare Pages Build Configuration

## Current Status

✅ **Monorepo wrapper created** — Root-level `package.json` now supports `npm run build` from repository root

## How It Works

1. **Cloudflare Pages** executes: `npm run build`
2. **Root `package.json`** redirects to: `cd olav-web && npm install && npm run build`
3. **olav-web Astro** builds site to: `dist/`
4. **Cloudflare** serves from: `dist/` directory

## Cloudflare Dashboard Configuration

**If build still fails, verify these settings:**

### Settings → Build & deployments

| Setting | Value |
|---------|-------|
| **Build command** | `npm run build` |
| **Build output directory** | `dist` |
| **Node.js version** | ≥ 18 |
| **Root directory** | (leave empty) |

**Note:** Do NOT set "Root directory" to `olav-web` — the wrapper package.json handles this automatically.

## Files Created

| File | Purpose |
|------|---------|
| `/package.json` | Root-level npm wrapper for Cloudflare Pages |
| `/build.sh` | Alternative bash build script |
| `/wrangler.json` | Cloudflare Workers/Pages configuration (optional) |

## Testing Locally

```bash
# Simulate Cloudflare Pages build
npm run build

# Output should go to: olav-web/dist/
```

## Troubleshooting

**If `npm run build` fails:**

1. Verify olav-web exists:
   ```bash
   ls -la olav-web/package.json
   ```

2. Check Node.js version:
   ```bash
   node --version  # Should be ≥ 18
   ```

3. Manually test from root:
   ```bash
   cd olav-web && npm install && npm run build && ls dist/
   ```

4. If Cloudflare still shows error, check: **CloudFlare Dashboard → Build & deployments → Build logs**

## Next Deploy

The next GitHub push (to any branch with Pages set up) will trigger Cloudflare Pages to rebuild using the new wrapper.
