#!/usr/bin/env python3
"""
添加命令白名单检查到 QueryRouter
"""


def add_whitelist_check() -> None:
    """在 route() 方法开始处添加命令白名单检查"""

    # 读取文件
    input_file = "src/olav/core/query_router.py"
    output_file = "src/olav/core/query_router.py"

    with open(input_file, encoding="utf-8") as f:
        content = f.read()

    # 找到 "Step 1: Guard检查" 的结束位置
    # 这是最高的优先级检查，白名单应该在这里

    # 在 Step 1 之后添加白名单检查代码
    whitelist_code = """

        # Step 1.5: 命令白名单检查 (Tier 0.5 - 快速路径，最高优先级)
        whitelist_file = Path(".olav/config/command_whitelist.yaml")
        if whitelist_file.exists():
            import yaml
            try:
                with open(whitelist_file) as f:
                    whitelist_config = yaml.safe_load(f)
                    command_whitelist = whitelist_config.get("command_whitelist", {})
                    mode = whitelist_config.get("mode", "simple_match")

                if mode == "simple_match" and user_input.strip():
                    for pattern, sql_query in command_whitelist.items():
                        if re.match(pattern, user_input.strip()):
                            device = self._extract_device_from_pattern(pattern, user_input)
                            params = {"sql": sql_query, "device": device}

                            decision = RoutingDecision(
                                expert="database",
                                action="route",
                                tool="query_database",
                                params=params,
                                message=f"Whitelist match: {pattern}",
                            )

                            return decision
            except Exception:
                pass  # 白名单检查失败不影响其他路径

"""

    # 找到第一个 "Step 2" 注释的位置
    marker = "        # Step 2: 斜杠命令检查"

    if marker in content:
        # 在标记之前插入白名单代码
        content = content.replace(marker, whitelist_code + marker)

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(content)

        print("✅ 已添加命令白名单检查到 QueryRouter")
        print("   - 位置: Step 1.5 (Step 2 之前)")
        print("   - 优先级: 最高 (在 Guard 检查之后)")

    else:
        print("❌ 未找到插入点")
        print("   请检查文件结构")


if __name__ == "__main__":
    add_whitelist_check()
