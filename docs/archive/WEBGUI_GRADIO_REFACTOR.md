# OLAV WebGUI Gradio 重构方案

## 概述

本文档提出使用 **Gradio** 替换现有 **Next.js** WebGUI 的重构方案，旨在：
1. 消除 SSR 水合（Hydration）问题
2. 简化 SSE 流式处理
3. 移除 LangServe 依赖，直接调用 Python 后端
4. 减少代码量约 60%
5. 保持与现有 UI 布局基本一致

## 架构对比

### 当前架构 (Next.js + LangServe)

```
┌─────────────┐    SSE/REST     ┌─────────────┐    LangServe    ┌─────────────┐
│   Next.js   │ ────────────────→│   FastAPI   │ ────────────────→│  LangGraph  │
│   WebGUI    │    fetch SSE    │   Server    │   add_routes    │ Orchestrator│
└─────────────┘                 └─────────────┘                 └─────────────┘
     ↓
  Zustand Store (SSR 水合问题)
  SSE 事件解析 (格式不匹配)
  TypeScript 类型维护
```

**问题**：
- SSR 与 Zustand persist 的水合时序问题
- LangServe SSE 事件格式与前端解析不匹配
- 需要维护 TypeScript 类型与 Pydantic 模型同步
- 代码量大：~3500 行 TypeScript/TSX

### 新架构 (Gradio + 直接调用)

```
┌─────────────┐    内嵌/挂载     ┌─────────────┐    直接调用     ┌─────────────┐
│   Gradio    │ ────────────────→│   FastAPI   │ ────────────────→│  LangGraph  │
│     UI      │   gr.mount()    │   Server    │   await graph   │ Orchestrator│
└─────────────┘                 └─────────────┘                 └─────────────┘
     ↓
  原生 Python 状态管理 (无水合问题)
  yield 原生流式 (无 SSE 解析)
  共享 Pydantic 模型 (零类型维护)
```

**优势**：
- 纯 Python，无 SSR/水合问题
- `yield` 原生流式，无需 SSE 解析
- 共享后端 Pydantic 模型
- 代码量：预计 ~800 行 Python

---

## UI 布局设计

### 整体布局 (与现有 Next.js 版本一致)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              OLAV WebGUI                                    │
├────────────────┬────────────────────────────────────────────────────────────┤
│                │                                                            │
│   ☰  展开/收起  │                     主聊天区域                              │
│                │                                                            │
│   + 新会话     │  ┌──────────────────────────────────────────────────────┐  │
│                │  │ [User]: 查询 R1 的 BGP 邻居状态                       │  │
│   ━━━━━━━━━━━━ │  └──────────────────────────────────────────────────────┘  │
│                │                                                            │
│   📝 会话历史   │  ┌──────────────────────────────────────────────────────┐  │
│                │  │ [Assistant]: 🧠 思考中...                             │  │
│   • BGP 状态查询│  │                                                       │  │
│   • OSPF 检查   │  │ ┌─────────────────────────────────────────────────┐  │  │
│   • 网络审计    │  │ │ 🔧 调用工具: suzieq_query                        │  │  │
│                │  │ │    table: bgp, method: get                      │  │  │
│   ━━━━━━━━━━━━ │  │ └─────────────────────────────────────────────────┘  │  │
│                │  │                                                       │  │
│   ⚙️ 设置      │  │ BGP Neighbors:                                       │  │
│                │  │ | Peer      | State  | Uptime     |                  │  │
│                │  │ |-----------|--------|------------|                  │  │
│                │  │ | 10.0.0.2  | Estab  | 5d 12:34   |                  │  │
│                │  └──────────────────────────────────────────────────────┘  │
│                │                                                            │
│                │  ┌──────────────────────────────────────────────────────┐  │
│                │  │ 🔍 工具 ▼ │ 输入您的问题...              │ 🗑️ │ ➤ │  │
│                │  └──────────────────────────────────────────────────────┘  │
└────────────────┴────────────────────────────────────────────────────────────┘
```

### 功能组件映射

| Next.js 组件 | Gradio 等效 | 说明 |
|-------------|-------------|------|
| `SessionSidebar` | `gr.Column` + `gr.Radio/Dataframe` | 会话历史列表 |
| `MessageBubble` | `gr.Chatbot` | 消息气泡渲染 |
| `ThinkingPanel` | `gr.Accordion` + `gr.Markdown` | 思考过程折叠 |
| `ToolIndicator` | `gr.Markdown` with animation | 工具调用指示 |
| `HITLDialog` | `gr.Modal` / `gr.Column(visible=...)` | HITL 审批弹窗 |
| `ExecutionLogPanel` | `gr.Accordion` | 执行日志 |
| `SettingsPanel` | `gr.Tab` / `gr.Accordion` | 设置面板 |
| `ToolsMenu` | `gr.Dropdown` | 工具选择 |
| `InspectionModal` | `gr.Tab` | 巡检管理 |
| `DocumentModal` | `gr.Tab` | 文档管理 |

---

## 详细实现方案

### 1. 文件结构

```
src/olav/ui/
├── __init__.py
├── gradio_app.py          # 主 Gradio 应用 (~400 行)
├── components/
│   ├── __init__.py
│   ├── chat.py            # 聊天组件 (~150 行)
│   ├── sidebar.py         # 侧边栏组件 (~100 行)
│   ├── hitl.py            # HITL 弹窗组件 (~80 行)
│   └── settings.py        # 设置组件 (~50 行)
├── state.py               # 状态管理 (~50 行)
└── utils.py               # 工具函数 (~30 行)
```

**总计**: ~800-900 行 Python (vs 现有 ~3500 行 TypeScript)

### 2. 主应用入口 (`gradio_app.py`)

```python
"""OLAV Gradio WebGUI - 主应用入口"""

import gradio as gr
from typing import Generator
import asyncio

from olav.core.settings import settings
from olav.agents.root_agent_orchestrator import create_workflow_orchestrator
from olav.ui.state import SessionState
from olav.ui.components.chat import create_chat_interface
from olav.ui.components.sidebar import create_sidebar
from olav.ui.components.hitl import create_hitl_modal
from olav.ui.components.settings import create_settings_panel

# 全局 Orchestrator (启动时初始化)
orchestrator = None
checkpointer = None


async def init_orchestrator():
    """初始化工作流编排器"""
    global orchestrator, checkpointer
    result = await create_workflow_orchestrator(expert_mode=settings.expert_mode)
    orchestrator_obj, stateful_graph, stateless_graph, checkpointer_manager = result
    orchestrator = stateless_graph
    checkpointer = checkpointer_manager
    return orchestrator


def create_app() -> gr.Blocks:
    """创建 Gradio 应用"""
    
    # 自定义 CSS
    css = """
    /* 整体布局 */
    .main-container { display: flex; height: 100vh; }
    .sidebar { width: 280px; border-right: 1px solid #e5e7eb; }
    .sidebar.collapsed { width: 56px; }
    .chat-area { flex: 1; display: flex; flex-direction: column; }
    
    /* 消息样式 */
    .user-message { background: #3b82f6; color: white; border-radius: 12px; }
    .assistant-message { background: #f3f4f6; border-radius: 12px; }
    
    /* 思考过程 */
    .thinking-panel { 
        background: rgba(234, 179, 8, 0.1); 
        border: 1px solid rgba(234, 179, 8, 0.2);
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 8px;
    }
    
    /* 工具调用 */
    .tool-indicator {
        background: rgba(59, 130, 246, 0.1);
        border: 1px solid rgba(59, 130, 246, 0.2);
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 8px;
    }
    
    /* HITL 弹窗 */
    .hitl-modal {
        position: fixed;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        background: white;
        border-radius: 12px;
        box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
        padding: 24px;
        z-index: 1000;
    }
    
    /* 表格样式 (Markdown 表格) */
    table { border-collapse: collapse; width: 100%; margin: 8px 0; }
    th, td { border: 1px solid #e5e7eb; padding: 8px 12px; text-align: left; }
    th { background: #f9fafb; font-weight: 600; }
    tr:hover { background: #f9fafb; }
    """
    
    with gr.Blocks(
        title="OLAV - Enterprise Network Operations",
        css=css,
        theme=gr.themes.Soft(
            primary_hue="blue",
            secondary_hue="gray",
        ),
    ) as app:
        # ========================================
        # 状态变量
        # ========================================
        session_state = gr.State(SessionState())
        current_session_id = gr.State(None)
        is_authenticated = gr.State(False)
        sidebar_collapsed = gr.State(False)
        hitl_pending = gr.State(None)  # 待审批的 HITL 事件
        
        # ========================================
        # 登录页面 (未认证时显示)
        # ========================================
        with gr.Column(visible=True, elem_id="login-page") as login_page:
            gr.Markdown("# 🔐 OLAV WebGUI")
            gr.Markdown("请输入 Access Token 进行认证")
            
            token_input = gr.Textbox(
                label="Access Token",
                placeholder="粘贴服务器启动时打印的 Token...",
                type="password",
            )
            login_btn = gr.Button("验证并进入", variant="primary")
            login_error = gr.Markdown(visible=False)
            
            gr.Markdown("""
            ---
            💡 **Token 获取方式**: 查看服务器启动日志中的 `ACCESS TOKEN`
            
            🔗 或直接使用日志中打印的 WebGUI URL (自动携带 token)
            """)
        
        # ========================================
        # 主界面 (认证后显示)
        # ========================================
        with gr.Row(visible=False, elem_id="main-app") as main_app:
            # ----------------------------------------
            # 左侧边栏
            # ----------------------------------------
            with gr.Column(
                scale=1, 
                min_width=280, 
                elem_classes=["sidebar"],
            ) as sidebar:
                # 折叠/展开按钮
                with gr.Row():
                    collapse_btn = gr.Button("☰", size="sm", elem_id="collapse-btn")
                    new_chat_btn = gr.Button("+ 新会话", size="sm", variant="secondary")
                
                gr.Markdown("### 📝 会话历史")
                
                # 会话列表
                session_list = gr.Dataframe(
                    headers=["会话", "时间", "消息数"],
                    datatype=["str", "str", "number"],
                    interactive=False,
                    elem_id="session-list",
                )
                
                # 底部设置
                gr.Markdown("---")
                settings_btn = gr.Button("⚙️ 设置", size="sm")
            
            # ----------------------------------------
            # 主聊天区域
            # ----------------------------------------
            with gr.Column(scale=4, elem_classes=["chat-area"]) as chat_area:
                # 标题栏
                gr.Markdown("# OLAV", elem_id="chat-header")
                
                # 聊天消息
                chatbot = gr.Chatbot(
                    label="对话",
                    height=500,
                    show_label=False,
                    avatar_images=(
                        None,  # User avatar
                        "https://raw.githubusercontent.com/langchain-ai/langchain/master/docs/static/img/langchain.png",  # Bot avatar
                    ),
                    render_markdown=True,
                    elem_id="chatbot",
                )
                
                # 执行日志 (可折叠)
                with gr.Accordion("📋 执行日志", open=False, visible=False) as exec_log_panel:
                    exec_log = gr.Markdown("暂无执行日志")
                
                # 输入区域
                with gr.Row():
                    tool_dropdown = gr.Dropdown(
                        choices=["🔍 标准查询", "🚀 深度分析", "📊 巡检", "📄 文档"],
                        value="🔍 标准查询",
                        label="工具",
                        scale=1,
                        min_width=120,
                    )
                    user_input = gr.Textbox(
                        placeholder="输入您的问题...",
                        label="消息",
                        scale=6,
                        show_label=False,
                    )
                    clear_btn = gr.Button("🗑️", size="sm", scale=0)
                    send_btn = gr.Button("➤ 发送", variant="primary", scale=1)
                    stop_btn = gr.Button("■ 停止", variant="stop", scale=1, visible=False)
        
        # ========================================
        # HITL 审批弹窗
        # ========================================
        with gr.Column(visible=False, elem_classes=["hitl-modal"]) as hitl_modal:
            gr.Markdown("## ⚠️ 操作需要审批")
            hitl_device = gr.Markdown("**目标设备**: -")
            hitl_operation = gr.Markdown("**操作类型**: -")
            hitl_commands = gr.Code(label="待执行命令", language="bash")
            hitl_risk = gr.Markdown("**风险等级**: 🟡 中")
            
            with gr.Row():
                hitl_reject = gr.Button("❌ 拒绝", variant="secondary")
                hitl_approve = gr.Button("✅ 批准执行", variant="primary")
        
        # ========================================
        # 设置面板
        # ========================================
        with gr.Column(visible=False) as settings_panel:
            gr.Markdown("## ⚙️ 设置")
            
            language_dropdown = gr.Dropdown(
                choices=["中文", "English"],
                value="中文",
                label="界面语言",
            )
            
            gr.Markdown("### LLM 配置 (只读)")
            gr.Textbox(value=settings.llm_provider, label="Provider", interactive=False)
            gr.Textbox(value=settings.llm_model_name, label="Model", interactive=False)
            
            close_settings_btn = gr.Button("关闭", size="sm")
        
        # ========================================
        # 事件处理函数
        # ========================================
        
        def validate_token(token: str):
            """验证 Token"""
            from olav.server.auth import verify_token
            try:
                user = verify_token(token)
                if user:
                    return (
                        True,  # is_authenticated
                        gr.update(visible=False),  # login_page
                        gr.update(visible=True),   # main_app
                        gr.update(visible=False),  # login_error
                        token,  # store token
                    )
            except Exception:
                pass
            
            return (
                False,
                gr.update(visible=True),
                gr.update(visible=False),
                gr.update(value="❌ Token 无效或已过期", visible=True),
                None,
            )
        
        async def stream_response(
            message: str, 
            history: list, 
            session_state: SessionState,
            tool_mode: str,
        ) -> Generator:
            """流式生成响应"""
            global orchestrator
            
            if not orchestrator:
                await init_orchestrator()
            
            # 构建消息
            from langchain_core.messages import HumanMessage, AIMessage
            messages = []
            for user_msg, bot_msg in history:
                if user_msg:
                    messages.append(HumanMessage(content=user_msg))
                if bot_msg:
                    messages.append(AIMessage(content=bot_msg))
            messages.append(HumanMessage(content=message))
            
            # 构建输入
            input_state = {
                "messages": messages,
                "workflow_type": None,
                "iteration_count": 0,
                "interrupted": False,
                "execution_plan": None,
            }
            
            # 流式执行
            current_response = ""
            thinking_log = []
            tool_log = []
            
            history = history + [(message, None)]
            
            async for event in orchestrator.astream(input_state):
                # 解析事件
                if "route_to_workflow" in event:
                    workflow_state = event["route_to_workflow"]
                    msgs = workflow_state.get("messages", [])
                    if msgs:
                        last_msg = msgs[-1]
                        if hasattr(last_msg, "content"):
                            content = last_msg.content
                            if content and content != current_response:
                                current_response = content
                                history[-1] = (message, current_response)
                                yield history, thinking_log, tool_log
                
                # 处理工具调用
                if "tool_calls" in str(event):
                    # 提取工具信息
                    tool_info = f"🔧 工具调用: {event}"
                    tool_log.append(tool_info)
                    yield history, thinking_log, tool_log
            
            # 最终结果
            yield history, thinking_log, tool_log
        
        def clear_chat():
            """清空聊天"""
            return [], []
        
        def toggle_sidebar(collapsed: bool):
            """切换侧边栏"""
            return not collapsed
        
        def load_session(session_id: str, token: str):
            """加载历史会话"""
            from olav.ui.utils import fetch_session_messages
            try:
                messages = fetch_session_messages(session_id, token)
                history = []
                for msg in messages:
                    if msg["role"] == "user":
                        history.append((msg["content"], None))
                    else:
                        if history and history[-1][1] is None:
                            history[-1] = (history[-1][0], msg["content"])
                        else:
                            history.append((None, msg["content"]))
                return history
            except Exception:
                return []
        
        def refresh_sessions(token: str):
            """刷新会话列表"""
            from olav.ui.utils import fetch_sessions
            try:
                sessions = fetch_sessions(token)
                data = [
                    [s.get("first_message", "新会话")[:30], s.get("updated_at", "")[:16], s.get("message_count", 0)]
                    for s in sessions
                ]
                return data
            except Exception:
                return []
        
        # ========================================
        # 绑定事件
        # ========================================
        
        # 登录
        login_btn.click(
            validate_token,
            inputs=[token_input],
            outputs=[is_authenticated, login_page, main_app, login_error, session_state],
        )
        
        # 发送消息
        send_btn.click(
            stream_response,
            inputs=[user_input, chatbot, session_state, tool_dropdown],
            outputs=[chatbot, exec_log, exec_log],
        ).then(
            lambda: "",
            outputs=[user_input],
        )
        
        # 回车发送
        user_input.submit(
            stream_response,
            inputs=[user_input, chatbot, session_state, tool_dropdown],
            outputs=[chatbot, exec_log, exec_log],
        ).then(
            lambda: "",
            outputs=[user_input],
        )
        
        # 清空聊天
        clear_btn.click(
            clear_chat,
            outputs=[chatbot, exec_log],
        )
        
        # 新会话
        new_chat_btn.click(
            clear_chat,
            outputs=[chatbot, exec_log],
        )
        
        # 折叠侧边栏
        collapse_btn.click(
            toggle_sidebar,
            inputs=[sidebar_collapsed],
            outputs=[sidebar_collapsed],
        )
        
        # 设置面板
        settings_btn.click(
            lambda: gr.update(visible=True),
            outputs=[settings_panel],
        )
        close_settings_btn.click(
            lambda: gr.update(visible=False),
            outputs=[settings_panel],
        )
        
        # HITL 审批
        hitl_approve.click(
            lambda: (gr.update(visible=False), True),
            outputs=[hitl_modal, hitl_pending],
        )
        hitl_reject.click(
            lambda: (gr.update(visible=False), False),
            outputs=[hitl_modal, hitl_pending],
        )
    
    return app


def mount_to_fastapi(fastapi_app):
    """将 Gradio 挂载到 FastAPI"""
    gradio_app = create_app()
    return gr.mount_gradio_app(fastapi_app, gradio_app, path="/ui")


if __name__ == "__main__":
    app = create_app()
    app.launch(
        server_name="0.0.0.0",
        server_port=3100,
        share=False,
    )
```

### 3. 状态管理 (`state.py`)

```python
"""Gradio 应用状态管理"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class ThinkingStep:
    """思考步骤"""
    step: int
    content: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ToolEvent:
    """工具调用事件"""
    name: str
    args: dict
    result: Optional[str] = None
    success: bool = True
    duration_ms: Optional[float] = None


@dataclass
class HITLEvent:
    """HITL 审批事件"""
    plan_id: str
    device: str
    operation: str
    commands: list[str]
    risk_level: str  # "low", "medium", "high"


@dataclass
class SessionState:
    """会话状态"""
    token: Optional[str] = None
    current_session_id: Optional[str] = None
    is_streaming: bool = False
    
    # 执行日志
    thinking_steps: list[ThinkingStep] = field(default_factory=list)
    tool_events: list[ToolEvent] = field(default_factory=list)
    
    # HITL
    pending_hitl: Optional[HITLEvent] = None
    
    def clear(self):
        """清空状态"""
        self.current_session_id = None
        self.is_streaming = False
        self.thinking_steps = []
        self.tool_events = []
        self.pending_hitl = None
```

### 4. 工具函数 (`utils.py`)

```python
"""Gradio UI 工具函数"""

import httpx
from typing import Optional


def fetch_sessions(token: str, limit: int = 50) -> list[dict]:
    """获取会话列表"""
    from olav.core.settings import settings
    
    url = f"http://localhost:{settings.server_port}/sessions"
    headers = {"Authorization": f"Bearer {token}"}
    
    with httpx.Client() as client:
        response = client.get(url, headers=headers, params={"limit": limit})
        response.raise_for_status()
        data = response.json()
        return data.get("sessions", [])


def fetch_session_messages(session_id: str, token: str) -> list[dict]:
    """获取会话消息"""
    from olav.core.settings import settings
    
    url = f"http://localhost:{settings.server_port}/sessions/{session_id}"
    headers = {"Authorization": f"Bearer {token}"}
    
    with httpx.Client() as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data.get("messages", [])


def delete_session(session_id: str, token: str) -> bool:
    """删除会话"""
    from olav.core.settings import settings
    
    url = f"http://localhost:{settings.server_port}/sessions/{session_id}"
    headers = {"Authorization": f"Bearer {token}"}
    
    with httpx.Client() as client:
        response = client.delete(url, headers=headers)
        return response.status_code == 200


def format_timestamp(timestamp: str) -> str:
    """格式化时间戳"""
    from datetime import datetime
    
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        now = datetime.now(dt.tzinfo)
        diff = now - dt
        
        if diff.days == 0:
            return dt.strftime("%H:%M")
        elif diff.days == 1:
            return "昨天"
        elif diff.days < 7:
            return f"{diff.days} 天前"
        else:
            return dt.strftime("%m-%d")
    except Exception:
        return timestamp[:16]
```

---

## 集成方案

### 方案 A: 挂载到现有 FastAPI (推荐)

修改 `src/olav/server/app.py`:

```python
from olav.ui.gradio_app import mount_to_fastapi

def create_app() -> FastAPI:
    app = FastAPI(...)
    
    # ... 现有代码 ...
    
    # 挂载 Gradio UI
    mount_to_fastapi(app)
    
    return app
```

**访问**: `http://localhost:8001/ui`

### 方案 B: 独立进程运行

```python
# src/olav/ui/__main__.py
from olav.ui.gradio_app import create_app

if __name__ == "__main__":
    app = create_app()
    app.launch(server_port=3100)
```

**运行**: `uv run python -m olav.ui`

### 方案 C: Docker Compose 集成

```yaml
# docker-compose.yml
services:
  olav-webgui:
    build:
      context: .
      dockerfile: Dockerfile.gradio
    ports:
      - "3100:3100"
    environment:
      - OLAV_API_URL=http://olav-server:8001
    depends_on:
      - olav-server
```

---

## 迁移步骤

### Phase 1: 基础框架 (2 小时)

1. 创建 `src/olav/ui/` 目录结构
2. 实现 `gradio_app.py` 主应用
3. 实现 Token 认证页面
4. 测试登录流程

### Phase 2: 聊天功能 (2 小时)

1. 实现 `gr.Chatbot` 流式对话
2. 接入 Orchestrator 流式输出
3. 实现思考过程显示
4. 实现工具调用指示

### Phase 3: 侧边栏 (1 小时)

1. 实现会话历史列表
2. 实现会话切换
3. 实现会话删除
4. 实现折叠/展开

### Phase 4: 高级功能 (1 小时)

1. 实现 HITL 审批弹窗
2. 实现设置面板
3. 实现巡检入口
4. 实现文档管理入口

### Phase 5: 清理 (30 分钟)

1. 删除 `webgui/` 目录
2. 删除 `docker-compose.yml` 中 `olav-webgui` 服务
3. 移除 LangServe `add_routes()` 调用 (可选)
4. 更新文档

---

## 代码量对比

| 模块 | Next.js (行数) | Gradio (预估) | 减少 |
|------|---------------|---------------|------|
| 主应用 | ~300 (page.tsx) | ~200 | 33% |
| 聊天组件 | ~200 (message-bubble, chat-store) | ~100 | 50% |
| 侧边栏 | ~250 (session-sidebar, session-store) | ~80 | 68% |
| HITL | ~150 (hitl-dialog) | ~50 | 67% |
| 设置 | ~100 (settings-panel) | ~30 | 70% |
| 认证 | ~200 (auth-store, auth-guard, login) | ~50 | 75% |
| API 客户端 | ~300 (client.ts, types.ts) | ~30 (直接调用) | 90% |
| 状态管理 | ~400 (stores/*.ts) | ~50 | 88% |
| 样式 | ~200 (globals.css, tailwind) | ~100 (内联 CSS) | 50% |
| **总计** | **~3500** | **~800** | **77%** |

---

## 功能对比表

| 功能 | Next.js 当前状态 | Gradio 实现难度 | 说明 |
|------|-----------------|----------------|------|
| Token 认证 | ⚠️ 水合问题 | ✅ 简单 | 纯 Python，无水合 |
| 流式输出 | ⚠️ SSE 解析问题 | ✅ 简单 | `yield` 原生流式 |
| Markdown 表格 | ⚠️ 需额外 CSS | ✅ 内置 | `gr.Chatbot` 支持 |
| 会话历史 | ⚠️ 刷新问题 | ✅ 简单 | 直接调用 API |
| HITL 审批 | ✅ 正常 | ✅ 简单 | `gr.Column(visible=...)` |
| 侧边栏折叠 | ✅ 正常 | ✅ 简单 | CSS 类切换 |
| 执行日志 | ✅ 正常 | ✅ 简单 | `gr.Accordion` |
| 停止按钮 | ✅ 正常 | ✅ 简单 | `gr.Button.click(..., cancels=[...])` |
| 深色模式 | ✅ 正常 | ✅ 内置 | `gr.themes.Soft` |
| 国际化 | ✅ 正常 | ⚠️ 手动 | 需自行实现 |
| 巡检管理 | ✅ 正常 | ✅ 简单 | `gr.Tab` |
| 文档上传 | ✅ 正常 | ✅ 内置 | `gr.File` |

---

## 风险与注意事项

### 1. UI 美观度

- **风险**: Gradio 默认主题可能不如定制的 shadcn/ui 精致
- **缓解**: 使用自定义 CSS + `gr.themes.Soft` 接近现有风格

### 2. 复杂交互

- **风险**: 侧边栏折叠动画可能不如 Next.js 流畅
- **缓解**: 使用 CSS `transition` 实现基础动画

### 3. SEO/SSR

- **风险**: Gradio 不支持 SSR
- **影响**: 对于内部工具 WebGUI，SEO 不重要，可忽略

### 4. 学习曲线

- **风险**: 团队需要学习 Gradio API
- **缓解**: Gradio 文档完善，API 简单

---

## 总结

| 维度 | Next.js | Gradio |
|------|---------|--------|
| 代码量 | ~3500 行 | ~800 行 |
| 复杂度 | 高 (SSR、水合、SSE) | 低 (纯 Python) |
| 维护成本 | 需 TypeScript + React 经验 | 仅需 Python |
| 部署复杂度 | 独立容器 + Node.js | 与后端同一进程 |
| 流式支持 | SSE 解析复杂 | `yield` 原生 |
| 已知问题 | 4 个未解决 | 无 |

**建议**: 考虑到当前 Next.js 版本存在 4 个持续性问题（Token 持久化、流式显示、Markdown 表格、会话刷新），且修复这些问题需要深入理解 Next.js SSR 机制和 LangServe SSE 格式，**采用 Gradio 重构是更务实的选择**。

---

## 附录: Gradio 版 UI 预览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           OLAV - 企业网络运维平台                            │
├────────────────┬────────────────────────────────────────────────────────────┤
│ ☰              │                                                            │
│ + 新会话       │   👤 查询 R1 的 BGP 邻居状态                                │
│ ━━━━━━━━━━━━━━ │   ────────────────────────────────────────────────────────  │
│ 📝 会话历史    │   🤖 正在分析查询意图...                                    │
│                │                                                            │
│ • BGP 状态查询 │   ┌─────────────────────────────────────────────────────┐  │
│   今天 10:23   │   │ 🧠 思考过程                                   [▼]   │  │
│   5 条消息     │   │ 1. 识别查询意图: BGP 邻居状态                       │  │
│                │   │ 2. 选择工具: suzieq_query                          │  │
│ • OSPF 检查    │   └─────────────────────────────────────────────────────┘  │
│   昨天         │                                                            │
│   3 条消息     │   ┌─────────────────────────────────────────────────────┐  │
│                │   │ 🔧 调用工具: suzieq_query                           │  │
│ ━━━━━━━━━━━━━━ │   │    table: bgp, hostname: R1, method: get           │  │
│                │   └─────────────────────────────────────────────────────┘  │
│ ⚙️ 设置        │                                                            │
│                │   R1 的 BGP 邻居状态如下:                                  │
│                │                                                            │
│                │   | Peer      | State       | Uptime      | Prefixes |    │
│                │   |-----------|-------------|-------------|----------|    │
│                │   | 10.0.0.2  | Established | 5d 12:34:56 | 42       |    │
│                │   | 10.0.0.3  | Established | 3d 08:21:15 | 38       |    │
│                │                                                            │
├────────────────┼────────────────────────────────────────────────────────────┤
│                │ 🔍 标准 ▼ │ 输入您的问题...                    │ 🗑️ │ ➤ │ │
└────────────────┴────────────────────────────────────────────────────────────┘
```

---

## 下一步

1. **确认方案**: 决定是否采用 Gradio 重构
2. **创建分支**: `git checkout -b feature/gradio-webgui`
3. **实现 Phase 1**: 基础框架 + 登录
4. **迭代测试**: 逐步添加功能并测试
5. **清理**: 删除 Next.js 代码，更新文档
