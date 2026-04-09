# 掘金文章 Workflow

## 内容指引

读 [content-strategy.md](../../content-writer/references/content-strategy.md) → 掘金 部分再写内容。

**语气**：实用技术类，直接给干货，中文开发者口语（"咱们"、"踩坑"、"搞定"都可以）。

---

## 内容生成（浏览器操作前必须完成）

草稿在 `olav-post/archive/YYYY-MM-DD/juejin.md` — 由 `content-writer` 生成。
读取草稿，确认通过以下自查项目后再打开浏览器。

### 强制自查

```
[ ] 没有"赋能"、"强大"、"全面"、"无缝"、"革命性"、"业界领先"
[ ] 前言直接切入问题，不是"大家好，今天分享..."
[ ] 包含至少一个代码片段或 CLI 命令
[ ] 包含"踩过的坑"段落（真实问题，非泛泛而谈）
[ ] 代码块格式正确（掘金支持 Markdown）
[ ] 语气是中文开发者口语（"咱们"、"搞定"可以；"赋能"不行）
[ ] 内容与知乎草稿是不同角度（知乎讲 why，掘金讲 how）
```

---

## Browser Workflow（Chrome DevTools MCP）

### 1. 打开掘金新建草稿页

```
mcp_chrome-devtoo_navigate_page → url: "https://juejin.cn/editor/drafts/new?v=2"
mcp_chrome-devtoo_wait_for → text: ["文章将自动保存至草稿箱", "字符数"]
mcp_chrome-devtoo_take_snapshot → 确认页面加载完成
```

**登录检查**：如果未出现 "文章将自动保存至草稿箱" 提示，停止，提示用户登录。

### 2. 填写标题

```
mcp_chrome-devtoo_take_snapshot → 找标题输入框（selector: .title-input）
mcp_chrome-devtoo_click → 标题 ref
mcp_chrome-devtoo_type_text → 准备好的文章标题
```

### 3. 填写正文（Markdown 编辑器）

掘金编辑器底层是 bytemd（包含 CodeMirror），使用 Markdown 格式。

```
mcp_chrome-devtoo_evaluate_script → 定位并 focus 编辑器：
  document.querySelector('.bytemd-editor .CodeMirror textarea').focus()
mcp_chrome-devtoo_take_snapshot → 确认编辑区 focus
mcp_chrome-devtoo_click → 编辑区 ref（.bytemd-editor .CodeMirror textarea）
mcp_chrome-devtoo_type_text → 准备好的 Markdown 正文
mcp_chrome-devtoo_press_key → key: "Enter"  （触发编辑器状态同步）
```

等待自动保存（约2秒）：
```
mcp_chrome-devtoo_wait_for → text: ["保存成功", "草稿箱"]  timeout: 5000
mcp_chrome-devtoo_take_snapshot → 确认页面出现"保存成功"或类似提示
```

### 4. 设置封面图（发布前必须）

掘金发布时需要封面图（封面图在"发布"弹窗中设置，草稿阶段可先跳过，但需提醒用户）。

> **备注给用户**：请在手动发布时，在弹出的"发布"对话框中上传封面图：
> 文件位于 `olav-web/public/blog-images/<slug>/og-image.webp`

如果发布弹窗在 MCP 操作期间出现：
```
mcp_chrome-devtoo_take_snapshot → 找封面图上传区域
mcp_chrome-devtoo_upload_file
  uid: <封面图 input ref>
  filePath: /home/yhvh/Olav/olav-post/archive/YYYY-MM-DD/images/og-image.webp
```

### 5. 确认草稿已保存（禁止发布）

掘金会自动保存草稿——无需手动点击保存按钮。

观察页面顶部是否出现"保存成功"提示。

**绝对禁止点击"发布"按钮。**

### 6. 视觉确认 + 汇报用户

```
mcp_chrome-devtoo_take_screenshot → 截图编辑器当前状态（标题+正文可见）
```

立即汇报用户：
- 截图（标题、正文均可见）
- 自动保存状态：已确认"保存成功" / 未确认
- 草稿地址：`https://juejin.cn/user/drafts`
- 确认信息："草稿已保存，请前往掘金草稿箱审查后手动发布（发布时需选分类、标签、封面图）。"

---

## 故障排查

| 问题 | 处理方式 |
|---|---|
| 页面加载空白 | 刷新后重试；确认已登录 |
| 标题无法输入 | 用 `mcp_chrome-devtoo_fill` 替代 `type_text` |
| 正文 textarea 找不到 | 尝试 selector: `.CodeMirror textarea` 直接定位 |
| 自动保存未触发 | 多按几次 Enter 或 Space 触发状态变化 |
| 重复 ref 问题 | 优先用 CSS selector `.CodeMirror textarea` 而不是 snapshot ref 编号 |

## 备注

- 掘金草稿 URL 格式：`https://juejin.cn/editor/drafts/<draft_id>`
- 编辑器正文区可能在 `snapshot -i` 中出现多个 `textbox` ref，用 CSS selector 更可靠
