#!/usr/bin/env python3
"""覆盖率检查脚本 - 运行 E2E 测试并验证覆盖率."""

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / "src/olav"
REQUIRED_COVERAGE = 80


def run_coverage_check() -> int:
    """运行 E2E 测试并检查覆盖率."""
    # 运行 E2E 测试
    subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            "tests/00_e2e_acceptance_test.py",
            f"--cov={SRC_DIR}",
            "--cov-report=json:coverage.json",
            "--cov-report=term",
            "-q",
            "--tb=no",
            "-x",  # 第一个失败停止
        ],
        cwd=PROJECT_ROOT,
        timeout=1200,
        check=False,
    )

    # 读取覆盖率报告
    coverage_file = PROJECT_ROOT / "coverage.json"
    if coverage_file.exists():
        try:
            with open(coverage_file) as f:
                data = json.load(f)

            total = data.get("totals", {}).get("percent_covered", 0)
            print(f"\n{'=' * 70}")
            print("📊 覆盖率报告")
            print(f"{'=' * 70}")
            print(f"总体覆盖率: {total:.1f}%")
            print(f"目标覆盖率: {REQUIRED_COVERAGE}%")

            if total >= REQUIRED_COVERAGE:
                print(f"\n✅ 覆盖率已达到目标 ({total:.1f}% >= {REQUIRED_COVERAGE}%)")
                return 0
            else:
                print(f"\n❌ 覆盖率未达到目标 ({total:.1f}% < {REQUIRED_COVERAGE}%)")
                print("\n📈 覆盖率最低的 10 个文件:")
                files = data.get("files", {})
                low_cov = sorted(
                    [
                        (
                            Path(name).name,
                            fdata.get("summary", {}).get("percent_covered", 0),
                        )
                        for name, fdata in files.items()
                    ],
                    key=lambda x: x[1],
                )
                for fname, pct in low_cov[:10]:
                    print(f"  {pct:5.1f}% | {fname}")
                return 1
        except (json.JSONDecodeError, KeyError) as e:
            print(f"❌ 解析覆盖率报告失败: {e}")
            return 1
    else:
        print("❌ 覆盖率文件不存在")
        return 1


if __name__ == "__main__":
    sys.exit(run_coverage_check())
