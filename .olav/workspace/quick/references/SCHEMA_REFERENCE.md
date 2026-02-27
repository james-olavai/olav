# 📊 Quick SQL Reference & Examples

**Global Filter Requirement**: In every query, ensure you filter by `snapshot_id = (SELECT MAX(snapshot_id) FROM sync_metadata)`.

## 🗄️ Core Table Schema
| Table | Primary Columns | Description |
| :--- | :--- | :--- |
| **`devices`** | `hostname`, `ip`, `vendor`, `model`, `platform` | Inventory & base info |
| **`interfaces`** | `device_id`, `interface`, `ip_address`, `status`, `description` | L3 interface data |
| **`routes`** | `network`, `next_hop`, `protocol`, `device_id` | General routing table |
| **`bgp_routes`** | `network`, `next_hop`, `as_path`, `local_pref`, `device_id` | BGP specific attributes |
| **`topology_links`** | `local_device`, `local_port`, `remote_device`, `remote_port` | LLDP/CDP adjacency |
| **`parsed_outputs`**| `device_id`, `command`, `output` (JSON) | Raw parsed data |

---

## 💡 SQL Examples for Quick Generation

### 1. List all down interfaces on a specific device
```sql
SELECT interface, description, status 
FROM interfaces 
WHERE device_id = 'R1' 
AND status != 'up'
AND snapshot_id = (SELECT MAX(snapshot_id) FROM sync_metadata);
```

### 2. Find which device has a specific IP address
```sql
SELECT device_id, interface, ip_address 
FROM interfaces 
WHERE ip_address = '10.1.1.1'
AND snapshot_id = (SELECT MAX(snapshot_id) FROM sync_metadata);
```

### 3. Check BGP neighbors for a specific device
```sql
SELECT network, next_hop, as_path 
FROM bgp_routes 
WHERE device_id = 'SW1'
AND snapshot_id = (SELECT MAX(snapshot_id) FROM sync_metadata);
```

### 4. Find LLDP/CDP neighbors (Topology)
```sql
SELECT local_port, remote_device, remote_port 
FROM topology_links 
WHERE local_device = 'R2'
AND snapshot_id = (SELECT MAX(snapshot_id) FROM sync_metadata);
```

### 5. Search Raw JSON output (e.g., CPU load from custom command)
```sql
SELECT device_id, output->>'$.cpu_load' as cpu 
FROM parsed_outputs 
WHERE command = 'show process cpu'
AND snapshot_id = (SELECT MAX(snapshot_id) FROM sync_metadata);
```

---

## 🛠️ Fallback Rules
- If the query fails, call `execute_sql(explain_only=True)` to re-verify columns.
- Joining: Link tables using `device_id` matching `devices.hostname`.
