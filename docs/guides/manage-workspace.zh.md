# 管理工作空间

工作空间（`.olav/workspace/`）是 OLAV 所有 Agent 和 Skill 定义的存放地。你可以把它理解为 OLAV 的"能力库"——安装新技能、切换 Agent、管理版本，都在这里进行。

!!! abstract "功能声明"
    | ID | 声明 | 状态 |
    |----|------|------|
    | C-L2-03 | `olav workspace list/use` 列出并切换活跃 workspace | ✅ v0.10.0 |
    | C-L2-04 | `olav skill install <path>` 安装本地 Skill | ✅ v0.10.0 |
    | C-L2-36 | `olav skill list/status` 查看已安装技能 | ✅ v0.10.0 |
    | C-L2-43 | `olav workspace status` 显示 Agent 状态 | ✅ v0.10.0 |

---

## 查看工作空间

```bash
olav workspace list
```

```
  audit                 -       (user)
  config                -       (user)
  core                  -       (user)
* quick                 -       (user)    ← * = 当前活跃 Agent
  venv-test             v1.0.0  (managed) ← managed = 通过 olav skill install 安装
  verify-skill          v1.0.0  (managed)
```

两种来源：

- **(user)** — 手动创建在 `.olav/workspace/` 中的 Agent，通常是内置的或自定义的
- **(managed)** — 通过 `olav skill install` 安装的技能包

查看某个技能的详细信息：

```bash
olav skill status venv-test
```

```
name:    venv-test
version: 1.0.0
source:  /tmp/venv-test-skill
installed: 2026-03-31T05:32:54
```

---

## 切换活跃 Agent

活跃 Agent 是你运行 `olav` 或 `olav "问题"` 时默认使用的 Agent：

```bash
olav workspace use config     # 切换到 config Agent
olav workspace use quick      # 切回 quick Agent
```

切换后，所有不带 `--agent` 的查询都会路由到新的活跃 Agent。

---

## 安装技能

```bash
# 从本地目录安装（需要包含 MANIFEST.yaml 或 workspace.yaml）
olav skill install ./my-custom-tools/
# installed my-skill v0.1.0 → .olav/workspace/my-skill/

# 从 Git 仓库安装
olav skill install https://github.com/your-org/my-skill

# 将工具追加到已有 Agent
olav skill install ./extra/ --merge-into existing-skill
```

安装后立即可用，无需重启。详见 [构建自定义技能 →](build-a-skill.md)

---

## 卸载技能

直接删除工作空间目录：

```bash
rm -rf .olav/workspace/my-skill/
```

目前没有 `olav skill remove` 命令——文件系统删除就是卸载方式。

---

## 工作空间目录结构

```
.olav/workspace/
├── quick/                          ← 内置 Agent
│   ├── AGENT.md                    ← Agent 定义（名称、描述、系统提示词、子 Agent）
│   └── MANIFEST.yaml               ← 路由关键词、版本信息
├── config/                         ← 内置 Agent（含多个子技能）
│   ├── AGENT.md
│   ├── creator/SKILL.md            ← 子技能：Creator Agent（生成工具代码）
│   ├── discovery/SKILL.md          ← 子技能：服务发现
│   ├── knowledge/SKILL.md          ← 子技能：知识库管理
│   └── system/SKILL.md             ← 子技能：系统健康检查
└── venv-test/                      ← 安装的技能（managed）
    ├── MANIFEST.yaml
    ├── tools.py                    ← 工具函数
    └── .venv/                      ← 隔离的 Python 虚拟环境
```

### 关键文件说明

- **AGENT.md**：Agent 的"身份证"——定义了 Agent 的名称、职责描述、系统提示词、以及它可以调用哪些子 Agent/技能
- **MANIFEST.yaml**：技能的元数据——名称、版本号、路由关键词、依赖声明
- **SKILL.md**：子技能的绑定文件——将一组工具函数绑定到某个 Agent
- **tools.py**：实际的 Python 工具函数——Agent 可调用的 `@tool` 函数

---

## 版本控制

工作空间定义可以安全地提交到 Git，与团队共享：

```bash
git add .olav/workspace/
git commit -m "feat: add my-skill"
```

**不要提交的内容**（加入 `.gitignore`）：

```gitignore
.olav/databases/   # 数据库文件
.olav/config/      # 包含 API 密钥
.olav/run/         # 运行时 PID 文件
```

这样团队成员拉取代码后，就拥有相同的 Agent 定义和技能，只需要各自配置 `api.json` 即可使用。
