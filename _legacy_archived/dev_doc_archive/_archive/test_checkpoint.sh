#!/bin/bash
# Test OLAV checkpoint/memory functionality

echo "=== Test 1: New Session (显示session ID) ==="
echo -e "list devices\nexit" | uv run olav

echo ""
echo "=== Test 2: Resume Last Session (使用--resume) ==="
echo -e "show R1 interfaces\nexit" | uv run olav --resume

echo ""
echo "=== Test 3: Specific Thread ID (使用--thread-id) ==="
THREAD_ID=$(cat .olav/.last_thread_id)
echo "Using thread_id: $THREAD_ID"
echo -e "what did I ask before?\nexit" | uv run olav --thread-id "$THREAD_ID"

echo ""
echo "=== Test 4: Query Command (不使用checkpoint) ==="
uv run olav query "list ip addresses on R2"

echo ""
echo "✅ Checkpoint测试完成！"
echo ""
echo "使用方法："
echo "  olav                    # 新会话（随机ID）"
echo "  olav --resume           # 恢复上次会话"
echo "  olav --thread-id xxx    # 指定会话ID"
