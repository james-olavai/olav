#!/usr/bin/env python3
"""
清理旧缓存代码的脚本
"""

import re
from pathlib import Path


def clean_query_router():
    """清理 QueryRouter 中的旧缓存逻辑"""
    file_path = Path("src/olav/core/query_router.py")
    content = file_path.read_text(encoding="utf-8")

    # 移除 Tier 0 缓存检查调用
    content = re.sub(
        r"        # Tier 0: Semantic Cache.*?\n"
        r"        start = time\.time\(\)\n"
        r"        semantic_decision = self\._check_semantic_cache\(user_input\)\n"
        r'        timings\["semantic_cache"\] = time\.time\(\) - start\n'
        r"        if semantic_decision:\n"
        r"            semantic_decision\.timings = timings\n"
        r"            return semantic_decision\n\n",
        "",
        content,
        flags=re.DOTALL,
    )

    # 移除 _save_to_cache 调用
    content = re.sub(
        r"            # Save to cache for FastPath\n"
        r"            self\._save_to_cache\(user_input, pattern_match\)\n",
        "",
        content,
    )

    content = re.sub(
        r"            # Save to cache for FastPath\n"
        r"            self\._save_to_cache\(user_input, llm_decision\)\n",
        "",
        content,
    )

    content = re.sub(
        r"        # Save to cache for FastPath\n"
        r"        self\._save_to_cache\(user_input, decision\)\n",
        "",
        content,
    )

    # 移除 _check_semantic_cache 和 _save_to_cache 方法定义
    # 找到这两个方法，删除到下一个 def 之前
    lines = content.split("\n")
    new_lines = []
    skip_until_next_def = False
    indent_level = 0

    i = 0
    while i < len(lines):
        line = lines[i]

        if "    def _check_semantic_cache(" in line or "    def _save_to_cache(" in line:
            # 开始跳过
            skip_until_next_def = True
            indent_level = len(line) - len(line.lstrip())
            i += 1
            continue

        if skip_until_next_def:
            # 检查是否到达下一个 def
            if line.strip() and not line.strip().startswith("#"):
                current_indent = len(line) - len(line.lstrip())
                if current_indent <= indent_level and ("def " in line or "class " in line):
                    # 到达下一个方法/类定义
                    skip_until_next_def = False
                    new_lines.append(line)
                    i += 1
                    continue
            i += 1
            continue

        new_lines.append(line)
        i += 1

    content = "\n".join(new_lines)
    file_path.write_text(content, encoding="utf-8")
    print(f"✅ 已清理 {file_path}")


if __name__ == "__main__":
    clean_query_router()
