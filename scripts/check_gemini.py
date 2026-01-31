#!/usr/bin/env python3
"""
Check Gemni CLI installation and debug usage issues.
"""

import subprocess
import os
import sys

def check_gemini_in_path():
    """Check if gemini is in PATH."""
    try:
        result = subprocess.run(['which', 'gemini'], capture_output=True, text=True)
        print("✅ gemini in PATH:")
        print(f"   Location: {result.stdout.strip()}")
        print(f"   Symlink: {os.path.realpath(result.stdout.strip())}")
        return True
    except subprocess.CalledProcessError:
        print("❌ gemini NOT in PATH")
        return False

def check_nvm_gemini():
    """Check if gemini is available via nvm."""
    try:
        result = subprocess.run(['nvm', 'which', 'gemini'], capture_output=True, text=True)
        print("✅ gemini available via nvm:")
        print(f"   Location: {result.stdout.strip()}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ nvm which gemini failed: {e}")
        return False

def check_env_vars():
    """Check environment variables."""
    print("\n🔍 Environment Variables:")
    for var in ['GEMINI_API_KEY', 'GOOGLE_API_KEY', 'PATH']:
        value = os.environ.get(var)
        if value:
            print(f"   ✅ {var}: {value[:30]}... (set)")
        else:
            print(f"   ❌ {var}: (not set)")

def check_shell_config():
    """Check shell configuration."""
    print("\n🔍 Shell Configuration:")
    
    # Check if running in zsh or bash
    shell = os.environ.get('SHELL', '')
    print(f"   Shell: {shell}")
    
    # Check if gemini alias exists
    try:
        zsh_aliases = subprocess.run(['grep', '-e', '^alias gemini', '~/.zshrc'], capture_output=True, text=True)
        if zsh_aliases.stdout:
            print(f"   ✅ Zsh alias found: {zsh_aliases.stdout.strip()}")
    except:
        pass
    
    try:
        bash_aliases = subprocess.run(['grep', '-E', '^alias gemini', '~/.bashrc', '~/.bash_aliases'], capture_output=True, text=True)
        if bash_aliases.stdout:
            print(f"   ✅ Bash alias found: {bash_aliases.stdout.strip()}")
    except:
        pass

def test_gemini_execution():
    """Test if gemini can be executed."""
    print("\n🧪 Test Execution:")
    
    # Try direct execution
    try:
        result = subprocess.run(['~/.nvm/versions/node/v22.19.0/bin/gemini', 'models', 'list'], 
                       capture_output=True, text=True, timeout=10)
        print(f"   ✅ Direct execution: {result.stdout[:200]}")
    except Exception as e:
        print(f"   ❌ Direct execution failed: {e}")

def main():
    print("=" * 60)
    print("Gemini CLI Installation Check")
    print("=" * 60)
    print()
    
    # Step 1: Check PATH
    in_path = check_gemini_in_path()
    
    # Step 2: Check nvm
    nvm_available = check_nvm_gemini()
    
    # Step 3: Check environment
    check_env_vars()
    
    # Step 4: Check shell config
    check_shell_config()
    
    # Step 5: Test execution
    test_gemini_execution()
    
    print()
    print("=" * 60)
    print("💡 Diagnosis & Solutions")
    print("=" * 60)
    print()
    
    # Provide solutions
    if not in_path and not nvm_available:
        print("❌ Issue: gemini executable not found")
        print()
        print("Solutions:")
        print("1. Verify installation:")
        print("   - Run: which gemini")
        print("   - Run: ls -la ~/.nvm/versions/node/*/bin/")
        print()
        print("2. Add to PATH:")
        print("   - Add to ~/.bashrc: export PATH=\"\$HOME/.nvm/versions/node/v22.19.0/bin:\$PATH\"")
        print("   - Then run: source ~/.bashrc")
        print()
        print("3. Use nvm alias:")
        print("   - The binary exists at: ~/.nvm/versions/node/v22.19.0/bin/gemini")
        print("   - Create alias: alias gemini=\"~/.nvm/versions/node/v22.19.0/bin/gemini\"")
        print("   - Add to ~/.bashrc or ~/.zshrc")
        print()
        print("4. Check execution permissions:")
        print("   - Run: ls -l ~/.nvm/versions/node/v22.19.0/bin/gemini")
        print("   - Verify execute bit: chmod +x")
        print()
    
    print()
    print("=" * 60)
    print("✅ Check complete!")
    print("=" * 60)

if __name__ == "__main__":
    main()
