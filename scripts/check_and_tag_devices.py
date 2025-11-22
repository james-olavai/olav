import requests
import os

NETBOX_URL = "http://127.0.0.1:8080"
NETBOX_TOKEN = "5f0e3c6245275e54dcaf549121f7a32d7c132893"

headers = {"Authorization": f"Token {NETBOX_TOKEN}"}
r = requests.get(f"{NETBOX_URL}/api/dcim/devices/", headers=headers)
devices = r.json()["results"]

print(f"Total devices: {len(devices)}")
for d in devices:
    tags = [t["name"] for t in d.get("tags", [])]
    print(f"Device: {d['name']}, Tags: {tags}")

# Add tag if missing
tag_id = 1  # olav-managed tag ID
for d in devices:
    device_tags = [t["id"] for t in d.get("tags", [])]
    if tag_id not in device_tags:
        print(f"Adding olav-managed tag to {d['name']}")
        device_tags.append(tag_id)
        patch_data = {"tags": device_tags}
        r = requests.patch(f"{NETBOX_URL}/api/dcim/devices/{d['id']}/", headers=headers, json=patch_data)
        if r.status_code == 200:
            print(f"  ✓ Tagged {d['name']}")
        else:
            print(f"  ✗ Failed: {r.status_code} - {r.text}")
