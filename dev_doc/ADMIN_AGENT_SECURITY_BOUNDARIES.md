# Admin Agent 安全边界分析

**目的**: 明确Admin Agent的权限边界和安全限制
**日期**: 2026-02-12
**重要性**: 🔴 核心设计决策

---

## 三个核心问题

### 问题1: 应该修改Skill吗？

**背景**: Skill修改确实很麻烦，但修改Skill本质上是修改代码

#### ❌ 不应该让Agent修改Skill

**理由**:
1. **Skill是代码** - 修改Skill = 修改业务逻辑代码
   ```
   Skill文件结构:
   .olav/skills/xx-skill/
   ├── SKILL.md          # 配置元数据
   ├── prompts/          # LLM提示词
   ├── tools/            # Python工具代码
   ├── reference/        # 参考资料
   └── config/           # 配置文件
   ```

2. **Skill修改影响系统行为** - 不是简单的配置参数
   ```
   ❌ Agent修改Skill代码 → 可能引入bug
   ❌ Agent修改LLM提示词 → 可能改变行为
   ✅ Agent重新加载Skill → 立即生效
   ```

3. **没有版本控制保证** - Skill应通过Git管理
   ```
   正确做法:
   1. 开发者在IDE中修改Skill代码
   2. Git commit保存版本
   3. Agent只负责reload
   4. 出问题时可以rollback
   ```

4. **可能的错误场景**:
   ```
   User: "修改network-cli skill让它支持HP设备"
   
   ❌ 错误做法:
   Agent: 修改network-cli/tools/cli_executor.py
   结果: 代码改坏了，系统崩溃
   
   ✅ 正确做法:
   Agent: "需要修改Skill代码，请通过Git提交"
   开发者: 修改代码 → 测试 → commit → Agent reload
   ```

#### ✅ Agent应该能做:
- **查看Skill** - `list_skills`, `describe_skill`
- **重新加载Skill** - `reload_skill` (重加载SKILL.md配置)
- **查看Skill日志** - 看Skill执行情况
- **建议修改** - "你可能需要修改XX skill的YY功能"

---

### 问题2: 应该执行Shell/Python修复系统吗？

**背景**: 有时系统需要脚本修复，但这很危险

#### ❌ 不应该让Agent执行任意Shell/Python

**理由**:

1. **系统修复是高危操作**
   ```
   危险的Shell命令:
   - rm -rf /some/directory
   - ALTER TABLE devices DROP COLUMN *
   - export PASSWORD="xxx"  (敏感信息泄露)
   
   即使修复意图是好的，也可能:
   - 删错文件
   - 修复方案不当
   - 引入安全漏洞
   ```

2. **修复应该通过代码维护**
   ```
   ✅ 正确做法:
   1. 发现问题: "数据库连接失败"
   2. Admin: 报告问题给用户
   3. 开发者: 编写修复脚本，git commit
   4. 部署: 运行修复脚本 (有版本追溯)
   
   ❌ 错误做法:
   1. 发现问题
   2. Agent直接执行shell修复
   3. 没人知道做了什么
   4. 出问题时无法回滚
   ```

3. **没有审计追溯**
   ```
   Shell执行日志很难追踪原因:
   - 谁执行的？
   - 什么时候？
   - 为什么执行？
   - 具体命令是什么？
   - 有没有失败？
   ```

4. **修复脚本应该被版本控制**
   ```
   架构:
   .olav/
   ├── scripts/          # 这应该由开发者维护
   │   ├── repair_db.py
   │   ├── fix_cache.py
   │   └── ...
   └── cron/             # Agent可以定时执行预定脚本
       └── schedules.yaml (定义定时执行脚本)
   ```

#### ⚠️ 例外：预定义的修复脚本

如果脚本已经通过版本控制保存在代码库中：
```python
# .olav/scripts/repair_db.py (Git维护)
# 经过代码审查
# 有测试用例
# 文档齐全

则Agent可以:
1. 检测问题: "数据库连接失败"
2. 推荐脚本: "运行repair_db.py?"
3. 要求确认: "确定要运行吗? (y/n)"
4. 执行脚本: subprocess.run("python .olav/scripts/repair_db.py")
5. 报告结果和日志
```

#### ✅ Agent应该能做:
- **诊断问题** - 检查系统状态
- **建议解决方案** - "可能需要运行.olav/scripts/repair_cache.py"
- **执行预定义脚本** - 运行已版本控制的脚本(需要确认)
- **报告错误** - 发现问题后通知用户

---

### 问题3: 数据库和备份文件是核心资产

**原则**: 🔴 核心数据不能被Agent修改

#### 严格的读写限制

```
Asset             | Admin Agent | 开发者 | 备份系统 | 数据库
─────────────────┼─────────────┼────────┼─────────┼─────────
.olav/db/main.duckdb  | ❌ 读   | ⚠️修改 | ✅备份 | ✅操作
exports/backup_*.tar  | ❌ 读   | ⚠️管理 | ✅创建 | ❌触碰
.olav/knowledge/  | ✅ 添加MD | ✅修改 | ✅备份 | ❌直接改
.olav/config/     | ✅ 修改   | ✅修改 | ✅备份 | ❌直接改
logs/             | ✅ 读     | ✅分析 | ✅归档 | ❌修改
```

#### 数据库的保护措施

```python
# Admin Agent权限检查
class AdminAgent:
    async def handle_request(self, user_input: str):
        intent = await self.identify_intent(user_input)
        
        # 🔴 严格禁止数据库操作
        if "database" in intent or "db" in intent:
            if "delete" in intent or "modify" in intent:
                return "❌ 禁止修改数据库，这是核心资产"
        
        # 🔴 严格禁止修改备份文件
        if "backup" in intent and ("delete" in intent or "modify" in intent):
            return "❌ 禁止修改备份文件"
        
        # ✅ 允许的操作
        if intent == "add_device":
            return await self.add_device(**params)
        
        # ... 其他操作
```

---

## 修订后的Admin Agent权限矩阵

### 🟢 绿区 - 完全允许

| 功能 | 操作 | 文件 | 原因 |
|-----|------|------|------|
| **设备管理** | 添加/删除/修改 | `.olav/config/hosts.yaml` | 配置文件，可恢复 |
| **定时任务** | 创建/删除/修改 | `.olav/cron/schedules.yaml` | 配置文件，可恢复 |
| **知识库** | 添加/删除/修改 | `.olav/knowledge/*.md` | 配置文件，可恢复 |
| **系统配置** | 修改参数 | `.olav/settings.json` | 配置文件，可恢复 |
| **日志** | 读取/清理 | `logs/` | 只是日志，可重新生成 |
| **Skill** | 重新加载 | (内存操作) | 不修改代码 |
| **缓存** | 清理 | `.olav/cache/` | 临时数据，可重建 |

### 🟡 黄区 - 有条件允许

| 功能 | 条件 | 措施 |
|-----|------|------|
| **执行脚本** | 预定义的脚本 | 需要用户确认 |
| **修改环境变量** | 非敏感参数 | 限制特定变量 |
| **Skill重新加载** | 仅重新加载 | 不修改代码 |

### 🔴 红区 - 严格禁止

| 功能 | 原因 |
|-----|------|
| ❌ 修改数据库 | 核心业务数据 |
| ❌ 删除/修改备份 | 灾难恢复资产 |
| ❌ 修改Skill代码 | 应通过版本控制 |
| ❌ 执行任意Shell | 安全隐患 |
| ❌ 修改密钥/凭证 | 安全隐患 |
| ❌ 删除配置文件备份 | 无法恢复 |
| ❌ 修改core framework代码 | 影响系统稳定性 |

---

## 修改后的职责范围

### Admin Agent 能做的 (4类)

#### 1️⃣ 配置管理 (安全)
```
✅ 编辑: .olav/config/*.yaml, settings.json, knowledge/*.md
✅ 创建/删除配置条目
❌ 不修改: 数据库, 备份, 代码
```

#### 2️⃣ 系统监控 (安全)
```
✅ 读取: 日志, 系统状态, 性能指标
✅ 清理: 旧日志, 过期缓存
❌ 修改: 核心数据
```

#### 3️⃣ Skill管理 (安全)
```
✅ 查看: list_skills, describe_skill
✅ 重新加载: reload_skill (重加载SKILL.md)
❌ 修改: Skill代码
```

#### 4️⃣ 预定脚本执行 (有条件)
```
✅ 执行: .olav/scripts/ 中预定义的脚本
⚠️ 需要: 用户确认
❌ 执行: 任意shell命令
```

### Admin Agent 不能做的

```
❌ 数据库操作
❌ 备份文件修改
❌ Skill代码修改
❌ 任意Shell命令
❌ 敏感信息修改
❌ 框架代码修改
```

---

## 实现安全检查

### 方案: 操作白名单 + 黑名单

```python
class AdminAgent:
    # 允许修改的文件路径白名单
    ALLOWED_PATHS = [
        ".olav/config/hosts.yaml",
        ".olav/config/settings.json",
        ".olav/cron/schedules.yaml",
        ".olav/knowledge/*.md",
    ]
    
    # 禁止执行的命令黑名单
    FORBIDDEN_KEYWORDS = [
        "rm ", "del ", "drop table", "truncate",
        "ALTER TABLE", "DELETE FROM",
        "export PASSWORD", "export API_KEY",
        "git push", "git reset",
    ]
    
    # 允许执行的脚本白名单
    ALLOWED_SCRIPTS = [
        ".olav/scripts/repair_cache.py",
        ".olav/scripts/rebuild_index.py",
        # ... 其他预定义脚本
    ]
    
    async def handle_request(self, user_input: str):
        intent = await self.identify_intent(user_input)
        
        # 检查数据库操作
        if self._is_database_operation(intent):
            return "❌ 不允许修改数据库"
        
        # 检查备份操作
        if self._is_backup_modification(intent):
            return "❌ 不允许修改备份文件"
        
        # 检查代码修改
        if self._is_code_modification(intent):
            return "❌ 不允许修改代码，请通过Git提交"
        
        # 检查文件操作路径
        if self._is_file_operation(intent):
            if not self._is_allowed_path(intent):
                return "❌ 不允许操作该文件"
        
        # 检查Shell命令
        if self._is_shell_operation(intent):
            if not self._is_allowed_script(intent):
                return "❌ 不允许执行该命令"
        
        # 安全检查通过，执行操作
        return await self._execute_operation(intent)
```

---

## 修复系统 - 正确的流程

### 问题: 数据库连接失败

```
场景:
12:30 系统出现问题: "DuckDB连接失败"

❌ 错误的做法:
1. Admin Agent识别问题
2. Agent直接执行: "python .olav/scripts/fix_db.py"
3. 脚本修改数据库结构
4. 谁知道发生了什么？

✅ 正确的做法:

第一步: Agent诊断 (Admin Agent)
  Admin: "检测到数据库连接失败"
  Agent: 分析原因，查看日志
  
第二步: 报告给用户 (Admin Agent)
  Admin: "建议方案:
    Option 1: 运行.olav/scripts/rebuild_connection.py (推荐)
    Option 2: 检查数据库文件权限
    Option 3: 联系开发者
  "

第三步: 用户确认 (用户)
  User: "执行Option 1"

第四步: 执行脚本 (Admin Agent - 有条件)
  Agent: "即将运行repair_db.py，确认吗? (y/n)"
  User: "y"
  Agent: 执行脚本并记录日志

第五步: 报告结果 (Admin Agent)
  Agent: "修复完成
    - 操作: 运行rebuild_connection.py
    - 时间: 2026-02-12 12:35:00
    - 结果: 成功
    - 日志: [...]
  "
```

---

## 总结: Admin Agent的三层安全模型

```
第1层: 意图识别
  ↓
  检查是否是安全操作?
  ├─ ✅ 配置管理: "直接执行"
  ├─ ✅ 系统监控: "直接执行"
  ├─ ⚠️ 脚本执行: "要求用户确认"
  └─ ❌ 危险操作: "拒绝并说明原因"

第2层: 路径和权限检查
  ↓
  文件操作在允许列表中?
  ├─ ✅ .olav/config/*: 允许
  ├─ ✅ .olav/knowledge/*: 允许
  ├─ ✅ .olav/cron/*: 允许
  └─ ❌ 其他地方: 禁止

第3层: 内容安全检查
  ↓
  操作内容是否包含危险关键字?
  ├─ ❌ DROP TABLE: 禁止
  ├─ ❌ DELETE FROM: 禁止
  ├─ ❌ rm -rf: 禁止
  └─ ✅ 其他操作: 允许
```

---

## 对应的设计修改

需要在ADMIN_AGENT_SIMPLIFIED_DESIGN.md中补充：

1. ❌ **Admin不应该修改Skill代码** - 只能重新加载
2. ❌ **Admin不应该执行任意Shell** - 只能执行预定脚本(需确认)
3. ❌ **Admin严禁修改数据库** - 核心资产保护
4. ✅ **Admin可以执行预定脚本** - 但需要三层安全检查

---

**核心原则**: 

> Admin Agent的权限由大到小排序:
> 1. 配置文件修改 (SAFE)
> 2. 日志清理 (SAFE)
> 3. 预定脚本执行 (CONDITIONAL)
> 4. 系统诊断 (SAFE)
> 
> 禁止区:
> ❌ 数据库 / 备份 / 代码 / 任意Shell / 敏感信息
