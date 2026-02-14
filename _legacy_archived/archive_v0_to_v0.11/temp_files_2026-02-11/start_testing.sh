#!/bin/bash

# Level 1-P0 能力验证启动脚本

cd /home/yhvh/Olav

echo "🧪 Level 1-P0 能力验证"
echo "================================"
echo "场景1: 列出所有设备"
echo "命令: uv run olav ask 列出所有设备"
echo ""

# 测试1
echo "▶ 开始执行测试1..."
uv run olav ask "列出所有设备" 2>&1 | head -20
echo ""
echo "检查输出文件..."
ls -la exports/all_devices.csv 2>/dev/null || echo "文件不存在"
echo ""

# 等待3秒
sleep 3

echo "================================"
echo "场景2: 有多少个接口?"
echo "▶ 开始执行测试2..."
uv run olav ask "有多少个接口?" 2>&1 | head -20
echo ""
ls -la exports/*.csv exports/*.md 2>/dev/null | grep -E '(interface|count)' || echo "检查文件..."
echo ""

# 等待3秒
sleep 3

echo "================================"
echo "💾 测试执行完成"
echo "导出目录 (exports/) 中的文件:"
ls -la exports/ 2>/dev/null | tail -10
