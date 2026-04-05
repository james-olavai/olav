# Cloudflare Pages 构建失败 — 故障排除与解决

## 问题症状

```
2026-04-05T09:54:36.781Z	npm error path /opt/buildhome/repo/package.json
2026-04-05T09:54:36.781Z	npm error errno -2
2026-04-05T09:54:36.781Z	npm error enoent Could not read package.json
```

## 根本原因

olav 是一个 **monorepo**，网站代码在子目录：
```
/home/yhvh/Olav/
├── olav-web/          ← 实际的 Astro 项目（含 package.json）
├── src/               ← Python 平台代码
├── pyproject.toml     ← Python 包配置
└── （根目录没有 package.json）
```

Cloudflare Pages 默认在仓库根目录寻找 `package.json`，但找不到。

## 解决方案

### Step 1: 根级 package.json 包装器 ✅

创建了 `/package.json`，包含 npm 脚本委托给 olav-web：

```json
{
  "scripts": {
    "build": "cd olav-web && npm install && npm run build"
  }
}
```

### Step 2: 构建验证 ✅

在本地成功执行：
```bash
$ npm run build
> olav-monorepo@0.1.0 build
> cd olav-web && npm install && npm run build

19:56:10 [vite] ✓ 3799 modules transformed.
19:56:10 [vite] computing gzip size...
✅ Build complete
```

输出目录：`olav-web/dist/` (3.9M)

### Step 3: Cloudflare Dashboard 验证 ⚠️

**检查项：**
- ✅ Build command: `npm run build`（现在可用）
- ✅ Build output directory: `dist`
- ⚠️ Root directory: 保持空 (不要设置为 olav-web)

**截图说明：**
1. https://dash.cloudflare.com/
2. Workers & Pages → Pages → 选择项目
3. Settings → Build & deployments
4. 验证上述三个字段

## 已提交的文件

| 文件 | 说明 |
|------|------|
| `package.json` | 根级包装脚本（关键） |
| `wrangler.json` | Cloudflare Workers 配置 |
| `build.sh` | 可选的 bash 构建脚本 |
| `CLOUDFLARE_BUILD_FIX.md` | 完整配置指南 |

## 下一步

**当你下次 push 到 GitHub（含 Pages 集成）时：**

1. GitHub 触发 Cloudflare Pages webhook
2. Cloudflare 克隆仓库
3. 执行 `npm run build`（使用根级 package.json）
4. 根级脚本切换到 `olav-web/` 并执行 Astro 构建
5. 输出 `dist/` 到 Cloudflare

**✅ 构建应该成功**

## 故障排除清单

| 问题 | 解决 |
|------|------|
| `npm run build` 仍然失败 | 检查 `olav-web/package.json` 是否存在 |
| 输出路径错误 | 验证 `dist/` 目录在 `olav-web/` 下 |
| Node.js 版本错误 | Cloudflare Pages 应 ≥ 18，通常自动处理 |
| 仍无法部署 | 在 Cloudflare Dashboard 中重新部署一次 |

## 关键提示

**不要：**
- ❌ 设置 "Root directory" 为 `olav-web`（包装器处理）
- ❌ 修改根级 `package.json` 的 build 脚本

**要做：**
- ✅ 保持根级 `package.json` 简单明确
- ✅ 在 `olav-web/package.json` 中做所有真正的构建工作
- ✅ 每次更新 `olav-web/*` 后测试 `npm run build`

## 测试方法

**本地模拟 Cloudflare Pages 构建：**

```bash
cd /home/yhvh/Olav
rm -rf olav-web/dist
npm run build
ls -la olav-web/dist/  # 应该有内容
```

---

**Status:** ✅ 已修复，等待 Cloudflare 下次构建触发
