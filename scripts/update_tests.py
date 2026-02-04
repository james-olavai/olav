#!/usr/bin/env python3
"""更新test_acceptance.py: 删除淘汰功能,添加新测试"""

from pathlib import Path

TEST_FILE = Path("tests/e2e/test_acceptance.py")

# 读取文件
with open(TEST_FILE, "r", encoding="utf-8") as f:
    lines = f.readlines()

# 找到需要删除的测试并标记
delete_ranges = []

# 1. 找到 test_raw_file_count_matches_database
for i, line in enumerate(lines):
    if "def test_raw_file_count_matches_database" in line:
        start = i
        # 找到下一个def
        for j in range(i + 1, len(lines)):
            if lines[j].strip().startswith("def test_"):
                delete_ranges.append((start, j))
                print(f"标记删除 test_raw_file_count_matches_database: 行 {start + 1}-{j}")
                break
        break

# 2. 找到 test_parsed_directories_exist
for i, line in enumerate(lines):
    if "def test_parsed_directories_exist" in line:
        start = i
        # 找到下一个def
        for j in range(i + 1, len(lines)):
            if lines[j].strip().startswith("def test_"):
                delete_ranges.append((start, j))
                print(f"标记删除 test_parsed_directories_exist: 行 {start + 1}-{j}")
                break
        break

# 验证标记
print(f"\n总共标记删除 {len(delete_ranges)} 个测试")

# 先不删除,只报告
print("\n预览删除内容:")
for start, end in delete_ranges:
    print(f"\n{'=' * 60}")
    print(f"行 {start + 1}-{end}:")
    print("".join(lines[start:end]))
    print(f"{'=' * 60}")
