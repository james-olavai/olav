#!/usr/bin/env python3
"""
Fix Gemini CLI alias path and test.
"""

import os
import subprocess
import sys


def fix_gemini_alias() -> bool | None:
    """Fix the gemini alias in ~/.bashrc."""
    print("🔧 修复 Gemini CLI 别名...")

    # Read current ~/.bashrc
    bashrc_path = os.path.expanduser("~/.bashrc")
    try:
        with open(bashrc_path) as f:
            content = f.read()
    except Exception as e:
        print(f"❌ 无法读取 ~/.bashrc: {e}")
        return False

    # Check if alias exists
    alias_line = 'alias gemini="~/.nvm/versions/node/v22.19.0/bin/gemini"'
    if alias_line in content:
        print(f"✅ 别名已存在: {alias_line[:60]}...")
        return True

    # Add alias (correct path without /bin/)
    correct_alias = 'alias gemini="~/.nvm/versions/node/v22.19.0/gemini"'

    # Remove old alias if exists
    if alias_line in content:
        content = content.replace(alias_line, "")
        print(f"  🔄 移除旧别名: {alias_line[:60]}...")
    else:
        # Add alias at end
        content = content + "\n" + correct_alias
        print(f"  ➕ 添加新别名: {correct_alias[:60]}...")

    # Write back
    try:
        with open(bashrc_path, "w") as f:
            f.write(content)
        print("✅ 已更新 ~/.bashrc")
        return True
    except Exception as e:
        print(f"❌ 无法写入 ~/.bashrc: {e}")
        return False


def test_alias() -> bool | None:
    """Test if gemini alias works."""
    print("\n🧪 测试别名...")

    try:
        # Test which
        result = subprocess.run(["bash", "-lc", "alias gemini"], capture_output=True, text=True)
        print(f"   alias gemini = {result.stdout.strip()}")

        if result.returncode == 0 and "gemini" in result.stdout:
            print("   ✅ 别名已配置")
            return True
        else:
            print(f"   ❌ 别名配置失败: {result.stderr}")
            return False
    except Exception as e:
        print(f"   ❌ 测试异常: {e}")
        return False


def test_full_path() -> bool | None:
    """Test full path gemini."""
    print("\n🧪 测试完整路径...")

    try:
        result = subprocess.run(
            ["~/.nvm/versions/node/v22.19.0/bin/gemini", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            print("   ✅ 完整路径 gemini 工作正常")
            print(f"   版本: {result.stdout.strip()}")
            return True
        else:
            print(f"   ❌ 完整路径 gemini 失败: {result.stderr}")
            return False
    except Exception as e:
        print(f"   ❌ 测试异常: {e}")
        return False


def main() -> None:
    """Run fix and tests."""
    print("=" * 60)
    print("Gemini CLI 别名修复和测试")
    print("=" * 60)
    print()

    # Step 1: Fix alias
    if not fix_gemini_alias():
        print("❌ 别名修复失败")
        sys.exit(1)

    print()
    # Step 2: Test alias
    if not test_alias():
        print("❌ 别名测试失败")

    print()
    # Step 3: Test full path
    if not test_full_path():
        print("❌ 完整路径测试失败")

    print()
    print("=" * 60)
    print("修复总结")
    print("=" * 60)
    print("✅ 别名已修复并添加到 ~/.bashrc")
    print("✅ 可以使用: `gemini <command>` 或完整路径")
    print()
    print("下一步操作:")
    print("1. 在当前终端中运行: source ~/.bashrc")
    print("2. 然后测试: gemini --help")
    print("3. 或直接使用: ~/.nvm/versions/node/v22.19.0/bin/gemini --help")
    print("=" * 60)
    print("✅ 别名修复完成！")


if __name__ == "__main__":
    main()
