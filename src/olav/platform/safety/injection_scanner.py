"""
injection_scanner.py — Prompt 注入检测器

用于保护 Olav 的内存写入和 workspace 配置加载路径，
防止外部内容通过 LanceDB memory 或 SKILL.md/AGENT.md 注入恶意指令。

设计原则:
  - 纯函数，无副作用，无外部依赖
  - 检测到注入时拒绝写入，不崩溃
  - 误报优先于漏报（运维场景中 memory 内容应可信）

参考: dev_docs/15. hermes.md §3.3
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# ── 注入模式列表 ───────────────────────────────────────────────────────────────
# 按类别分组，便于调试和扩展

# 角色劫持 / 指令覆盖
_ROLE_HIJACK = [
    r"(?i)ignore\s+(all\s+)?previous\s+instructions?",
    r"(?i)disregard\s+(all|any|your|the\s+above)",
    r"(?i)you\s+are\s+now\s+(a|an)\s+\w",
    r"(?i)forget\s+(everything|all\s+previous|your\s+instructions?)",
    r"(?i)new\s+(system\s+)?instructions?\s*:",
    r"(?i)override\s+(your\s+)?(instructions?|rules?|guidelines?)",
    r"(?i)\[system\]",            # [system] 伪造角色标签
    r"(?i)<\s*system\s*>",        # <system> 伪造 XML 角色标签
]

# 数据外泄 payload
_EXFIL = [
    r"(?i)(curl|wget|nc|netcat|python3?\s+-c)\s+.*\b(secret|token|password|api.?key|[A-Z_]*key\b|key=)",
    r"(?i)ssh\s+.*authorized_keys",
    r"(?i)base64\s+.*\|\s*(curl|wget|sh|bash)",
    r"(?i)eval\s*\(\s*base64",
]

# 身份冒充 / 权限提升
_PRIVILEGE = [
    r"(?i)i\s+am\s+(an?\s+)?(admin|administrator|root|superuser|operator)",
    r"(?i)act\s+as\s+(if\s+you\s+are\s+(a\s+)?|a[n]?\s+)(admin|root|superuser)",
    r"(?i)grant\s+(me\s+)?(admin|root|all)\s+(access|permission|privilege)",
    r"(?i)sudo\s+su\b",
]

# 不可见/控制字符 (unicode 隐写攻击)
_INVISIBLE_UNICODE = re.compile(
    r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff\u00ad]"
)

INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(p) for p in (_ROLE_HIJACK + _EXFIL + _PRIVILEGE)
]


# ── 结果类型 ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class InjectionMatch:
    """注入检测命中结果。"""
    matched_pattern: str       # 命中的 pattern 描述
    matched_text: str          # 命中的原始文本片段（截断至 120 字符）
    category: str              # "role_hijack" | "exfil" | "privilege" | "invisible_unicode"


# ── 公开 API ──────────────────────────────────────────────────────────────────

def scan_content(text: str) -> tuple[bool, InjectionMatch | None]:
    """扫描文本是否包含 prompt 注入模式。

    Args:
        text: 待检查的文本内容（memory 条目、SKILL.md 内容等）

    Returns:
        ``(is_clean, match)``
        - ``is_clean=True, match=None``  → 内容安全，可以写入
        - ``is_clean=False, match=InjectionMatch``  → 检测到注入，拒绝写入

    Example::

        clean, match = scan_content(user_input)
        if not clean:
            logger.warning("Injection detected: %s", match)
            return {"status": "blocked", "reason": str(match)}
    """
    if not isinstance(text, str) or not text:
        return True, None

    # 1. 不可见 Unicode 字符检测
    if _INVISIBLE_UNICODE.search(text):
        # 找出哪些字符
        found = {unicodedata.name(c, repr(c)) for c in text if _INVISIBLE_UNICODE.match(c)}
        return False, InjectionMatch(
            matched_pattern="invisible_unicode",
            matched_text=f"Invisible unicode chars detected: {found}",
            category="invisible_unicode",
        )

    # 2. 正则模式匹配
    for idx, pattern in enumerate(INJECTION_PATTERNS):
        m = pattern.search(text)
        if m:
            # 确定类别
            n_role = len(_ROLE_HIJACK)
            n_exfil = len(_EXFIL)
            if idx < n_role:
                category = "role_hijack"
            elif idx < n_role + n_exfil:
                category = "exfil"
            else:
                category = "privilege"

            snippet = m.group(0)[:120]
            return False, InjectionMatch(
                matched_pattern=pattern.pattern,
                matched_text=snippet,
                category=category,
            )

    return True, None


def assert_clean(text: str, context: str = "content") -> None:
    """scan_content 的异常抛出版本，用于需要硬性阻断的路径。

    Args:
        text: 待检查文本
        context: 调用上下文描述（用于错误信息）

    Raises:
        ValueError: 检测到注入时抛出
    """
    is_clean, match = scan_content(text)
    if not is_clean:
        raise ValueError(
            f"[InjectionScanner] Blocked {context}: "
            f"category={match.category}, pattern={match.matched_pattern!r}"  # type: ignore[union-attr]
        )
