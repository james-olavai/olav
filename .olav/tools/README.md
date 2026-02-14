# OLAV Tools 使用指南

**位置**: `.olav/tools/` - MCP 标准兼容目录  
**版本**: v0.11 (2026-02-14)

---

## 📚 工具列表

### 1. inspection.py - 定时任务管理工具

**功能**: 管理网络检查定时任务（使用 python-crontab）

**Actions**:
- `schedule` - 创建/更新定时任务
- `unschedule` - 删除定时任务
- `list` - 列出所有定时任务
- `run` - 立即执行检查
- `status` - 查看执行历史
- `logs` - 查看日志内容

**使用方式**:

#### 方式 1: 通过 Agent（对话式，推荐）

```bash
# 设置定时任务
uv run olav ask "设置每天早上6点执行网络检查"

# 立即执行
uv run olav ask "立即执行网络检查"

# 查看状态
uv run olav ask "查看定时任务状态"

# 列出任务
uv run olav ask "列出所有定时任务"
```

Agent 会自动调用 `manage_inspection_schedule` tool。

#### 方式 2: 通过 CLI（快速）

```bash
# 设置定时任务（每天 06:00）
olav admin schedule daily-inspection "0 6 * * *"

# 立即执行
olav admin inspect run

# 查看状态（最近 7 天）
olav admin inspect status

# 查看日志
olav admin inspect logs --days 7

# 列出所有任务
olav admin inspect list

# 删除任务
olav admin unschedule daily-inspection
```

#### 方式 3: 直接调用 Tool（调试）

```bash
# 设置定时任务
echo '{"action":"schedule","schedule":"0 6 * * *"}' | python3 .olav/tools/inspection.py

# 列出任务
echo '{"action":"list"}' | python3 .olav/tools/inspection.py

# 立即执行
echo '{"action":"run"}' | python3 .olav/tools/inspection.py

# 查看状态
echo '{"action":"status","days":7}' | python3 .olav/tools/inspection.py

# 查看日志
echo '{"action":"logs","days":7}' | python3 .olav/tools/inspection.py
```

**返回格式**:

```json
{
  "status": "success",
  "action": "schedule",
  "message": "Scheduled daily-inspection at 0 6 * * *",
  "data": {
    "workflow": "daily-inspection",
    "schedule": "0 6 * * *",
    "enabled": true,
    "next_run": "2026-02-15 06:00:00"
  }
}
```

**验证安装**:

```bash
# 查看 crontab
crontab -l | grep OLAV

# 输出示例:
# OLAV-daily-inspection: 0 6 * * * cd /home/yhvh/Olav && uv run olav inspect daily-inspection
```

**日志位置**:
- 执行日志: `.olav/logs/inspection_YYYYMMDD.log`
- Cron 日志: `.olav/logs/cron.log`
- 报告输出: `exports/reports/snapshots/YYYYMMDD.md`

**特性**:
- ✅ Lock file 防止并发执行
- ✅ 30 分钟超时保护
- ✅ 详细日志记录
- ✅ Webhook 通知（可选）
- ✅ 错误处理和重试

---

## 📝 Tool 开发规范

### 目录结构

```
.olav/tools/
├── README.md           # 本文档
├── inspection.py       # 定时任务管理
├── database.py         # 数据库查询工具（规划中）
└── network.py          # 网络设备操作工具（规划中）
```

### Tool 开发模板

```python
#!/usr/bin/env python3
"""
Tool Name - Brief description

This tool provides...

Shared by: skill-name-1, skill-name-2

Usage:
    echo '{"param": "value"}' | python3 tool.py
"""

import json
import sys
from pydantic import BaseModel, Field
from langchain_core.tools import tool

# Pydantic Input Model
class ToolInput(BaseModel):
    param: str = Field(..., description="Parameter description")

# Pydantic Output Model
class ToolOutput(BaseModel):
    status: str = Field(..., description="success | failed")
    message: str | None = Field(None, description="Human-readable message")
    data: dict | None = Field(None, description="Additional data")
    error: str | None = Field(None, description="Error message if failed")

# LangChain Tool
@tool
def my_tool(param: str) -> dict:
    """Tool description for LLM
    
    Args:
        param: Parameter description
    
    Returns:
        {
            "status": "success | failed",
            "message": "...",
            "data": {...},
            "error": "..."
        }
    """
    try:
        # Tool logic here
        result = do_something(param)
        
        return ToolOutput(
            status="success",
            message="Operation completed",
            data=result
        ).dict()
    
    except Exception as e:
        return ToolOutput(
            status="failed",
            error=str(e)
        ).dict()

# CLI Entry Point
if __name__ == "__main__":
    try:
        input_json = sys.stdin.read()
        input_data = json.loads(input_json)
        
        result = my_tool(**input_data)
        
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["status"] == "success" else 1)
    
    except Exception as e:
        error_result = {
            "status": "failed",
            "error": str(e)
        }
        print(json.dumps(error_result, indent=2))
        sys.exit(1)
```

### 关键原则

1. **双模式支持**:
   - LangChain tool (Agent 调用)
   - Stdin JSON (CLI/脚本调用)

2. **Pydantic 验证**:
   - 输入: 使用 BaseModel 验证参数
   - 输出: 结构化返回（status, message, data, error）

3. **错误处理**:
   - 所有异常捕获并返回结构化错误
   - 适当的退出码（0/1）

4. **文档完整**:
   - Docstring 说明功能和参数
   - 顶部注释说明用途和使用方式
   - Shared by 标注哪些 Skill 使用

5. **独立可执行**:
   - 可通过 stdin 独立测试
   - 不依赖 Agent 环境

---

## 🔧 故障排查

### 问题: crontab 任务未执行

```bash
# 1. 检查任务是否存在
crontab -l | grep OLAV

# 2. 检查 cron 日志
tail -f /var/log/cron  # CentOS/RHEL
tail -f /var/log/syslog | grep CRON  # Ubuntu/Debian

# 3. 手动测试命令
cd /home/yhvh/Olav && uv run olav inspect daily-inspection

# 4. 检查权限
ls -la .olav/tools/inspection.py  # 应有执行权限
```

### 问题: Tool 返回错误

```bash
# 1. 直接测试 Tool
echo '{"action":"list"}' | python3 .olav/tools/inspection.py

# 2. 检查依赖
uv run python -c "import crontab; print(crontab.__version__)"

# 3. 查看详细日志
tail -f .olav/logs/inspection_$(date +%Y%m%d).log
```

### 问题: Agent 无法调用 Tool

```bash
# 1. 验证 Tool 注册
grep -A 5 "manage_inspection_schedule" .olav/AGENTS.md

# 2. 测试 Tool 导入
uv run python -c "from olav.tools.inspection import manage_inspection_schedule; print(manage_inspection_schedule)"

# 3. 检查 LLM 可见性
uv run olav ask "列出可用的工具"
```

---

## 📖 相关文档

- **完整设计**: `dev_docs/ADMIN_AND_CRON_DESIGN_v2.md`
- **架构文档**: `dev_docs/DEEPAGENTS_SIMPLIFICATION_PLAN.md`
- **测试参考**: `tests/e2e/test_inspection_tool.py`（规划中）

---

**最后更新**: 2026-02-14  
**版本**: v0.11  
**维护者**: OLAV Team
