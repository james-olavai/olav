#!/usr/bin/env python3
"""Test SSH connection using Scrapli (SuzieQ's SSH library)."""

from scrapli.driver.core import IOSXEDriver
import os

# Device info
device = {
    "host": "192.168.100.101",
    "auth_username": "cisco",
    "auth_password": os.getenv("DEVICE_PASSWORD", "cisco"),
    "auth_strict_key": False,
    "transport": "system",  # Use system SSH
}

print(f"Connecting to {device['host']}...")
print(f"Username: {device['auth_username']}")
print(f"Password: {device['auth_password']}")

try:
    conn = IOSXEDriver(**device)
    conn.open()
    print("✅ Connected successfully!")
    
    # Test command
    result = conn.send_command("show version | include IOS")
    print(f"\nCommand output:")
    print(result.result)
    
    conn.close()
    print("\n✅ Connection closed")
    
except Exception as e:
    print(f"❌ Connection failed: {e}")
    import traceback
    traceback.print_exc()
