#!/usr/bin/env python3
"""
Check Gemni CLI installation and debug usage issues.
"""

import subprocess
import os
import sys

def check_gemini_cli():
    """Check if gemini CLI is installed."""
    # Check common locations
    locations = [
        os.path.expanduser("~/.nvm/versions/node/v22.19.0/bin/gemini"),
        "/usr/local/bin/gemini",
        "/usr/bin/gemini",
        os.path.expanduser("~/bin/gemini"),
    ]
    
    for location in locations:
        if os.path.exists(location):
            print(f"Found at: {location}")
            return location
    
    print("gemini not found in standard locations")
    return None

def check_gemini_execution():
    """Test if gemini can be executed."""
    gemini_path = check_gemini_cli()
    
    if not gemini_path:
        print("Cannot test - gemini not found")
        return
    
    print(f"Testing gemini execution from: {gemini_path}")
    
    try:
        # Test help command
        result = subprocess.run([gemini_path, "--help"], capture_output=True, text=True, timeout=10)
        print(f"Success: gemini --help returned {result.returncode}")
        if result.returncode == 0:
            print("Output sample:")
            print(result.stdout[:200])
    except Exception as e:
        print(f"Execution failed: {e}")

def check_env_vars():
    """Check environment variables."""
    print("\nEnvironment Variables:")
    
    vars_to_check = [
        ("GEMINI_API_KEY", "Google API Key"),
        ("GOOGLE_API_KEY", "Alternative Google API Key"),
    ]
    
    for var, desc in vars_to_check:
        if var in os.environ:
            print(f"  {var}: {desc} - Set (length: {len(os.environ[var])})")
        else:
            print(f"  {var}: {desc} - Not set")
    
    # Check PATH
    path_var = os.environ.get("PATH", "")
    print(f"\nPATH:")
    print(f"  Contains 'gemini': {'/gemini/' in path_var or 'nvm' in path_var}")
    print(f"  Contains 'nvm': {'nvm' in path_var}")
    print(f"  Total PATH entries: {len(path_var.split(':'))}")

def check_nvm_gemini():
    """Check if gemini is available via nvm."""
    try:
        result = subprocess.run(["nvm", "which", "gemini"], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"nvm which gemini: {result.stdout.strip()}")
            return result.stdout.strip()
        else:
            print(f"nvm which gemini failed: {result.stderr}")
            return None
    except FileNotFoundError:
        print("nvm not available - checking PATH directly")
        return None
    except Exception as e:
        print(f"nvm check failed: {e}")
        return None

def test_direct_gemini():
    """Test direct gemini execution."""
    gemini_cli = check_gemini_cli()
    
    if gemini_cli:
        print(f"Testing direct execution of: {gemini_cli}")
        try:
            result = subprocess.run([gemini_cli, "--version"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                print(f"Success: {result.stdout.strip()}")
                return True
            else:
                print(f"Failed with code {result.returncode}")
                print(f"Error: {result.stderr}")
                return False
        except Exception as e:
            print(f"Execution failed: {e}")
            return False
    else:
        print("Cannot test - gemini CLI not found")
        return False

def main():
    """Run all checks."""
    print("=" * 60)
    print("Gemini CLI Installation & Usage Check")
    print("=" * 60)
    print()
    
    # Step 1: Check CLI installation
    print("Step 1: Checking gemini CLI installation...")
    gemini_cli = check_gemini_cli()
    
    # Step 2: Check nvm
    print("\nStep 2: Checking nvm integration...")
    nvm_gemini = check_nvm_gemini()
    
    # Step 3: Check environment
    print("\nStep 3: Checking environment variables...")
    check_env_vars()
    
    # Step 4: Test execution
    print("\nStep 4: Testing direct execution...")
    can_execute = test_direct_gemini()
    
    # Summary
    print("\n" + "=" * 60)
    print("Summary:")
    print("=" * 60)
    print(f"CLI Found: {gemini_cli if gemini_cli else 'Not found'}")
    print(f"NVM Available: {nvm_gemini if nvm_gemini else 'Not found'}")
    print(f"Can Execute: {can_execute if can_execute else 'No'}")
    print()
    
    # Diagnosis
    print("Diagnosis:")
    if gemini_cli:
        print("  gemini CLI is installed and executable")
        
        # Check if it's in PATH
        path_var = os.environ.get("PATH", "")
        in_path = gemini_cli in path_var
        print(f"  In PATH: {in_path}")
        
        if not in_path:
            print("  Issue: gemini executable but not in PATH")
            print("  Solutions:")
            print("    1. Add to PATH manually:")
            print(f"       export PATH=\"$PATH:{os.path.dirname(gemini_cli)}\"")
            print("    2. Create alias in ~/.bashrc:")
            print(f"       alias gemini=\"{gemini_cli}\"")
            print("    3. Use full path in scripts:")
            print(f"       {gemini_cli}")
        
        # Check if nvm is set up correctly
        if nvm_gemini != gemini_cli:
            print(f"  Issue: nvm points to {nvm_gemini} != {gemini_cli}")
            print("  Solutions:")
            print("    1. Install gemini via npm:")
            print("       npm install -g @google/gemini-cli")
            print("    2. Check nvm default:")
            print("       nvm alias default gemini")
    else:
        print("  Issue: gemini CLI not found")
        print("  Solutions:")
        print("    1. Install via npm: npm install -g @google/gemini-cli")
        print("    2. Install via yarn: yarn global add @google/gemini-cli")
        print("    3. Install via homebrew (Mac): brew install gemini")
    
    print()
    print("=" * 60)

if __name__ == "__main__":
    main()
