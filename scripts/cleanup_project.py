#!/usr/bin/env python3
"""
Phase 4.4 - 项目清理脚本

清理不必要的文件、缓存和垃圾代码

运行:
    uv run python scripts/cleanup_project.py
"""

import os
import shutil
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def cleanup_exports():
    """Clean up unnecessary export files"""
    logger.info("\n📁 清理导出文件...")
    
    exports_dir = Path("exports")
    if not exports_dir.exists():
        logger.info("   ✓ exports/ 不存在，无需清理")
        return
    
    # Keep only recent/important files
    benchmark_files = list((exports_dir / "benchmarks").glob("*.json")) if (exports_dir / "benchmarks").exists() else []
    quality_files = list((exports_dir / "quality_reports").glob("*.json")) if (exports_dir / "quality_reports").exists() else []
    
    logger.info(f"   ✓ 保留 {len(benchmark_files)} 个性能报告")
    logger.info(f"   ✓ 保留 {len(quality_files)} 个质量报告")
    
    # Legacy .csv files can stay for now (might have user value)
    csv_count = len(list(exports_dir.glob("*.csv")))
    logger.info(f"   ✓ 保留 {csv_count} 个 CSV 文件")


def cleanup_cache():
    """Clean up cache directories"""
    logger.info("\n🗑️  清理缓存...")
    
    cache_paths = [
        ".olav/.olav/cache/",
        ".olav/cache/",
        "src/olav/__pycache__",
        "tests/__pycache__",
        ".pytest_cache",
        ".ruff_cache",
    ]
    
    for cache_path in cache_paths:
        path = Path(cache_path)
        if path.exists():
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                    logger.info(f"   ✓ 删除: {cache_path}")
                else:
                    path.unlink()
                    logger.info(f"   ✓ 删除: {cache_path}")
            except Exception as e:
                logger.warning(f"   ⚠️  无法删除 {cache_path}: {e}")


def cleanup_temp_files():
    """Clean up temporary files"""
    logger.info("\n📄 清理临时文件...")
    
    temp_patterns = [
        ("*.tmp", "临时文件"),
        ("*.bak", "备份文件"),
        ("*.swp", "编辑器缓存"),
    ]
    
    for pattern, desc in temp_patterns:
        for file_path in Path(".").rglob(pattern):
            try:
                file_path.unlink()
                logger.info(f"   ✓ 删除: {file_path} ({desc})")
            except Exception as e:
                logger.warning(f"   ⚠️  无法删除 {file_path}: {e}")


def verify_code_structure():
    """Verify code structure compliance"""
    logger.info("\n✅ 验证代码结构...")
    
    # Check for required directories
    required = [
        "src/olav",
        "src/olav/agents",
        "src/olav/core",
        "src/olav/cli",
        "tests/e2e",
        "tests/performance",
        ".olav/skills",
    ]
    
    for path in required:
        p = Path(path)
        if p.exists():
            logger.info(f"   ✓ {path} ✅")
        else:
            logger.warning(f"   ⚠️  {path} 缺失")


def main():
    """Run cleanup"""
    logger.info("""
╔════════════════════════════════════════════════════════════╗
║            OLAV v2.0 项目清理 (Phase 4.4)                 ║
╚════════════════════════════════════════════════════════════╝
    """)
    
    logger.info("\n" + "="*60)
    logger.info("🧹 执行项目清理")
    logger.info("="*60)
    
    cleanup_exports()
    cleanup_cache()
    cleanup_temp_files()
    verify_code_structure()
    
    logger.info("\n" + "="*60)
    logger.info("✅ 清理完成")
    logger.info("="*60)
    logger.info("\n下一步: 运行最终验证测试")


if __name__ == "__main__":
    main()
