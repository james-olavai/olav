#!/bin/bash
# OLAV v0.9 E2E 真实 LLM + 真实设备测试
# 使用方法: bash tests/e2e_real_llm_test.sh

set -e

echo "=========================================="
echo "OLAV v0.9 E2E 真实环境测试"
echo "=========================================="
echo ""

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 测试计数
PASSED=0
FAILED=0
TOTAL=0

# 测试函数
test_query() {
    local test_name="$1"
    local query="$2"
    local expected_pattern="$3"
    
    TOTAL=$((TOTAL + 1))
    echo ""
    echo "----------------------------------------"
    echo "测试 $TOTAL: $test_name"
    echo "查询: $query"
    echo "----------------------------------------"
    
    # 运行查询并捕获输出
    output=$(echo "$query" | uv run olav 2>&1 | tee /tmp/olav_output_$TOTAL.txt)
    
    # 检查是否包含预期模式
    if echo "$output" | grep -qi "$expected_pattern"; then
        echo -e "${GREEN}✅ PASSED${NC}"
        PASSED=$((PASSED + 1))
    else
        echo -e "${RED}❌ FAILED${NC}"
        echo "期望包含: $expected_pattern"
        echo "实际输出见: /tmp/olav_output_$TOTAL.txt"
        FAILED=$((FAILED + 1))
    fi
}

# ============================================
# 阶段 1: 基础查询测试
# ============================================

echo ""
echo "=========================================="
echo "阶段 1: 基础查询测试"
echo "=========================================="

test_query "帮助命令" "help" "Available commands"

test_query "列出设备" "list devices" "device"

test_query "显示技能" "list skills" "skill"

# ============================================
# 阶段 2: 设备查询测试（需要真实设备）
# ============================================

echo ""
echo "=========================================="
echo "阶段 2: 设备查询测试"
echo "=========================================="

# 检查是否有 Nornir 配置
if [ -f ".olav/config/nornir/config.yaml" ] || [ -f ".olav/config/nornir/hosts.yaml" ]; then
    echo -e "${YELLOW}检测到 Nornir 配置，执行设备测试...${NC}"
    
    test_query "查询接口状态" "show interface status on all devices" "interface"
    
    test_query "查询系统版本" "what's the system version" "version"
    
    test_query "发现网络数据" "discover what data is available" "command\|snapshot\|data"
else
    echo -e "${YELLOW}⏭️  未检测到 Nornir 配置，跳过设备测试${NC}"
    echo "提示: Nornir 配置应位于 .olav/config/nornir/hosts.yaml"
fi

# ============================================
# 阶段 3: 数据分析测试
# ============================================

echo ""
echo "=========================================="
echo "阶段 3: 数据分析测试"
echo "=========================================="

# 检查是否有快照数据
if [ -d "exports/snapshots" ] && [ "$(ls -A exports/snapshots 2>/dev/null)" ]; then
    echo -e "${YELLOW}检测到快照数据，执行分析测试...${NC}"
    
    test_query "分析网络健康" "analyze network health" "health\|score\|status"
    
    test_query "检测错误" "find errors in the network" "error\|issue\|problem"
else
    echo -e "${YELLOW}⏭️  未检测到快照数据，跳过分析测试${NC}"
    echo "提示: 运行 'echo \"snapshot\" | uv run olav' 采集数据"
fi

# ============================================
# 阶段 4: Skill 执行测试
# ============================================

echo ""
echo "=========================================="
echo "阶段 4: Skill 执行测试"
echo "=========================================="

if [ -d ".olav/skills" ] && [ "$(ls -A .olav/skills 2>/dev/null)" ]; then
    echo -e "${YELLOW}检测到 Skills，执行 Skill 测试...${NC}"
    
    test_query "快速查询" "query device info" "device\|platform\|version"
    
    test_query "设备巡检" "inspect network devices" "inspection\|report\|device"
else
    echo -e "${YELLOW}⏭️  未检测到 Skills 目录，跳过 Skill 测试${NC}"
    echo "提示: 创建 .olav/skills/ 目录并添加 Skill"
fi

# ============================================
# 阶段 5: 工具集成测试
# ============================================

echo ""
echo "=========================================="
echo "阶段 5: 工具集成测试"
echo "=========================================="

test_query "搜索命令" "search for interface commands" "show\|interface"

test_query "搜索知识" "search knowledge about bgp" "bgp\|routing\|protocol"

# ============================================
# 测试总结
# ============================================

echo ""
echo "=========================================="
echo "测试总结"
echo "=========================================="
echo ""
echo "总测试数: $TOTAL"
echo -e "${GREEN}通过: $PASSED${NC}"
echo -e "${RED}失败: $FAILED${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ 所有测试通过！${NC}"
    echo ""
    echo "=========================================="
    echo "OLAV v0.9 E2E 验收测试完成"
    echo "状态: ✅ 成功"
    echo "=========================================="
    exit 0
else
    echo -e "${RED}❌ 有 $FAILED 个测试失败${NC}"
    echo ""
    echo "查看详细输出:"
    echo "  ls -lh /tmp/olav_output_*.txt"
    echo ""
    echo "=========================================="
    echo "OLAV v0.9 E2E 验收测试完成"
    echo "状态: ❌ 失败"
    echo "=========================================="
    exit 1
fi
