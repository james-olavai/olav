#!/usr/bin/env python3
"""Test NetBox connectivity from SuzieQ container."""

import requests

url = 'http://netbox:8080/api/dcim/devices/'
headers = {'Authorization': 'Token 5f0e3c6245275e54dcaf549121f7a32d7c132893'}

try:
    r = requests.get(url, headers=headers, timeout=5)
    print(f"NetBox API Status: {r.status_code}")
    
    if r.status_code == 200:
        data = r.json()
        print(f"Total devices: {data['count']}")
        print("\nDevices:")
        for device in data['results']:
            print(f"  - {device['name']}: {device['primary_ip4']['address'] if device.get('primary_ip4') else 'No IP'}")
    else:
        print(f"Error: {r.text[:200]}")
except Exception as e:
    print(f"Failed to connect: {e}")
