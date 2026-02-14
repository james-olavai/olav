#!/usr/bin/env python3
"""
Phase 4.3 - 代码质量检查报告生成

运行所有代码质量检查工具并生成报告

运行:
    uv run python scripts/generate_quality_report.py
"""

import subprocess
import json
from pathlib import Path
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def run_ruff_check():
    """Run Ruff code style check"""
    logger.info("🔍 Ruff 代码风格检查...")
    
    result = subprocess.run(
        ["uv", "run", "ruff", "check", "src/", "--extend-ignore", "ANN"],
        capture_output=True,
        text=True,
        cwd="/home/yhvh/Olav"
    )
    
    issues = result.stdout.count("-->")
    logger.info(f"   发现 {issues} 个问题")
    return {
        "tool": "ruff",
        "issues_count": issues,
        "passed": issues == 0,
        "output": result.stdout[:500]
    }


def run_pyright_check():
    """Run Pyright type checking"""
    logger.info("🔍 Pyright 类型检查...")
    
    result = subprocess.run(
        ["uv", "run", "pyright", "src/", "--outputjson"],
        capture_output=True,
        text=True,
        cwd="/home/yhvh/Olav"
    )
    
    # Extract error/warning count from output
    try:
        output = json.loads(result.stdout)
        errors = output.get("generalDiagnostics", [])
        error_count = len([e for e in errors if e.get("severity") == "error"])
        warning_count = len([e for e in errors if e.get("severity") == "warning"])
    except:
        error_count = result.stdout.count("error")
        warning_count = result.stdout.count("warning")
    
    logger.info(f"   错误: {error_count}, 警告: {warning_count}")
    return {
        "tool": "pyright",
        "errors": error_count,
        "warnings": warning_count,
        "passed": error_count == 0,
    }


def analyze_code_metrics():
    """Analyze code metrics"""
    logger.info("📊 代码指标分析...")
    
    # Count lines of code
    result = subprocess.run(
        ["find", "src/", "-name", "*.py", "-type", "f"],
        capture_output=True,
        text=True,
        cwd="/home/yhvh/Olav"
    )
    
    py_files = result.stdout.strip().split('\n')
    py_files = [f for f in py_files if f]
    
    total_lines = 0
    for py_file in py_files:
        try:
            with open(py_file, 'r') as f:
                total_lines += len(f.readlines())
        except:
            pass
    
    logger.info(f"   Python 文件数: {len(py_files)}")
    logger.info(f"   总代码行数: {total_lines}")
    
    return {
        "python_files": len(py_files),
        "total_lines_of_code": total_lines,
        "avg_lines_per_file": total_lines // len(py_files) if py_files else 0
    }


def main():
    """Generate quality report"""
    logger.info("""
╔════════════════════════════════════════════════════════════╗
║         OLAV v2.0 代码质量检查报告 (Phase 4.3)            ║
╚════════════════════════════════════════════════════════════╝
    """)
    
    report = {
        "timestamp": datetime.now().isoformat(),
        "version": "2.0.0",
        "checks": {}
    }
    
    logger.info("\n" + "="*60)
    logger.info("📊 运行代码质量检查")
    logger.info("="*60)
    
    # Run checks
    report["checks"]["ruff"] = run_ruff_check()
    report["checks"]["pyright"] = run_pyright_check()
    report["checks"]["metrics"] = analyze_code_metrics()
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("📋 质量检查总结")
    logger.info("="*60)
    
    ruff_ok = report["checks"]["ruff"]["passed"]
    pyright_ok = report["checks"]["pyright"]["passed"]
    
    logger.info(f"✅ Ruff: {'PASS ✅' if ruff_ok else 'FAIL ❌'}")
    logger.info(f"✅ Pyright: {report['checks']['pyright']['errors']} errors, {report['checks']['pyright']['warnings']} warnings")
    logger.info(f"📊 代码统计: {report['checks']['metrics']['python_files']} files, {report['checks']['metrics']['total_lines_of_code']} LOC")
    
    # Overall quality score (simplified)
    quality_score = 100
    if not ruff_ok:
        quality_score -= 10
    if not pyright_ok:
        quality_score -= 20
    
    logger.info(f"\n🎯 总体质量评分: {quality_score}/100")
    
    if quality_score >= 80:
        logger.info("✅ 质量达成预期 (>= 80%)")
    else:
        logger.warning(f"⚠️  质量需要改进 (< 80%)")
    
    # Save report
    output_file = Path("exports/quality_reports") / f"quality_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(report, f, indent=2)
    
    logger.info(f"\n💾 报告已保存: {output_file}")
    logger.info("\n" + "="*60)
    logger.info("✅ 质量检查完成")
    logger.info("="*60)


if __name__ == "__main__":
    main()
