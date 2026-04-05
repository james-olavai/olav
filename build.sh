#!/usr/bin/env bash
# Cloudflare Pages Build Script
# This handles the monorepo structure where olav-web is a subdirectory

set -e

echo "🚀 Cloudflare Pages Build - olav-web"
echo "Current directory: $(pwd)"
echo ""

# Navigate to olav-web directory
if [ ! -d "olav-web" ]; then
    echo "❌ ERROR: olav-web directory not found"
    exit 1
fi

cd olav-web

echo "📦 Installing dependencies..."
npm install || exit 1

echo ""
echo "🔨 Building Astro site..."
npm run build || exit 1

echo ""
echo "✅ Build complete!"
echo "Output: $(pwd)/dist"
