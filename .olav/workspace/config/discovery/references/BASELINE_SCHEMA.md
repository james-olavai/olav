# 📋 Cisco Baseline Schema Reference

Use this as the **Target Goal** for all Fuzzy Mapping and Data Normalization tasks.

## 1. Table: `interfaces`
| Column | Expected Format | Example |
| :--- | :--- | :--- |
| `status` | Case-insensitive: `up`, `down`, `admin-down` | `up` |
| `interface` | Full name or standard short form | `GigabitEthernet1/1` |
| `ip_address` | IPv4 address string | `10.1.1.1` |
| `description`| Free text | `Uplink to Core` |

## 2. Table: `bgp_neighbors`
| Column | Expected Format | Example |
| :--- | :--- | :--- |
| `state` | `Established`, `Idle`, `Active`, `Connect` | `Established` |
| `neighbor_ip`| IPv4 address string | `172.16.1.1` |
| `remote_as` | Integer | `65001` |

## 3. Table: `topology_links`
| Column | Expected Format | Example |
| :--- | :--- | :--- |
| `link_type` | `physical`, `logical` | `physical` |
| `local_port` | Must match `interfaces.interface` | `Gi1/0/1` |

## 💡 Mapping Rules for LLM
- If vendor is **Huawei**: Map `est` -> `Established`.
- If vendor is **Juniper**: Map `Testing` -> `down`.
- **Always** ensure IP fields are valid IPv4 format.
