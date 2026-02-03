#!/bin/bash
# E2E CLI Test Script
# Tests OLAV CLI with OpenRouter API

set -e

# Load environment from .env (filter out commented lines)
export OPENAI_API_KEY=$(grep '^LLM_API_KEY=' .env | cut -d= -f2-)
export OPENAI_API_BASE=$(grep '^LLM_BASE_URL=' .env | head -1 | cut -d= -f2-)
export LLM_MODEL_NAME="openai:x-ai/grok-4.1-fast"

echo "========================================="
echo "OLAV E2E CLI Test"
echo "========================================="
echo "API Base: $OPENAI_API_BASE"
echo "Model: $LLM_MODEL_NAME"
echo ""

echo "Test 1: Help Command"
echo "-----------------------------------------"
uv run olav --help | head -15
echo ""

echo "Test 2: Simple Query (Chinese)"
echo "-----------------------------------------"
echo "你好，OLAV，请简短介绍一下你自己（不超过50字）" | timeout 60 uv run olav 2>&1 | tail -20
echo ""

echo "Test 3: Simple Query (English)"
echo "-----------------------------------------"
echo "Hello OLAV, briefly introduce yourself (max 50 words)" | timeout 60 uv run olav 2>&1 | tail -20
echo ""

echo "========================================="
echo "E2E Test Complete"
echo "========================================="
