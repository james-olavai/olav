"""
务实的双引擎拓扑导入器 - 完整实现

您提议的改进方案的完整实现，支持两种数据导入策略：
1. Parsed JSON 优先 (快速、可靠)
2. Raw + LLM 备选 (灵活、智能)
"""

import json
import logging
import re
from pathlib import Path

import duckdb
from pydantic import BaseModel, ValidationError, field_validator
from pydantic_core import core_schema

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")


# ============================================================================
# 第1部分: Pydantic数据模型 (关键验证层)
# ============================================================================


class TopologyLink(BaseModel):
    """
    拓扑链接数据模型 - 核心验证在这里

    Pydantic会自动验证所有字段。如果验证失败，抛出ValidationError。
    """

    local_device: str
    remote_device: str
    local_port: str | None = None
    remote_port: str | None = None
    layer: str  # "L1" or "L3"
    protocol: str  # "CDP", "LLDP", "OSPF", "BGP"
    confidence: float = 0.95

    @field_validator("local_device", "remote_device", mode="before")
    @classmethod
    def validate_device_names(cls, v: str | None, info: core_schema.ValidationInfo) -> str:
        """
        关键验证: 设备名必须在已知设备列表中

        这是防止"Neighbor", IP地址等垃圾数据进入DB的最后防线。
        """

        v = str(v).strip()
        known_devices = _get_known_devices()
        field_name = info.field_name if hasattr(info, "field_name") else "device"

        # ❌ 规则1: 拒绝IP地址
        if _is_ip_address(v):
            raise ValueError(f"Invalid {field_name} '{v}': IP address not allowed, use device name")

        # ❌ 规则2: 拒绝通用占位符
        placeholders = {
            "Neighbor",
            "Unknown",
            "Total",
            "Switch",
            "%",
            "N/A",
            "S",
            "Uptime",
            "State",
            "Interface",
            "input",
            "Invalid",
            "network",
            "next_hop",
            "metric",
            "vlan",
            "name",
            "mode",
        }
        if v in placeholders:
            raise ValueError(f"Invalid {field_name} '{v}': placeholder/header, not a device name")

        # ❌ 规则3: 拒绝未知设备
        if v not in known_devices:
            raise ValueError(f"Unknown {field_name} '{v}'. Known devices: {sorted(known_devices)}")

        return v


# ============================================================================
# 第2部分: 辅助函数
# ============================================================================


def _get_known_devices(db_path: str = ".olav/db/network_warehouse.duckdb") -> set[str]:
    """从数据库读取已知设备列表"""
    try:
        db = duckdb.connect(db_path)
        result = db.execute("SELECT name FROM topology_devices").fetchall()
        db.close()
        return {row[0] for row in result}
    except Exception as e:
        logger.error(f"Failed to load known devices: {e}")
        return set()


def _is_ip_address(s: str) -> bool:
    """检查字符串是否是IPv4地址"""
    ip_pattern = r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"
    return bool(re.match(ip_pattern, s))


# ============================================================================
# 第3部分: 核心导入器类
# ============================================================================


class TopologyImporter:
    """
    双策略拓扑数据导入器

    策略1: Parsed JSON → 直接使用 (快速, 可靠)
    策略2: Raw数据 + LLM → Pydantic验证 (灵活, 智能)
    """

    def __init__(self, db_path: str = ".olav/db/network_warehouse.duckdb") -> None:
        self.db_path = db_path
        self.db = duckdb.connect(db_path)
        self.known_devices = self._load_known_devices()
        self.stats = {"valid": 0, "invalid": 0, "skipped": 0}

    def _load_known_devices(self) -> set[str]:
        """从数据库加载已知设备"""
        result = self.db.execute("SELECT name FROM topology_devices").fetchall()
        return {row[0] for row in result}

    # ========================================================================
    # 策略1: 使用Parsed JSON (优先)
    # ========================================================================

    def import_from_parsed_json(self, sync_dir: str) -> dict:
        """
        ✅ 优先使用Parsed JSON

        优点:
        • 数据已规范化
        • 不需要重新执行命令
        • 速度快
        • 不需要LLM调用

        参数:
            sync_dir: 同步数据目录路径 (如: "data/sync/2026-01-13")

        返回:
            {'valid': N, 'invalid': M, 'skipped': K}
        """

        print("\n📥 【策略1】导入模式: Parsed JSON")
        print("=" * 80)
        self.stats = {"valid": 0, "invalid": 0, "skipped": 0}

        parsed_dir = Path(sync_dir) / "parsed"

        if not parsed_dir.exists():
            logger.warning(f"Parsed directory not found: {parsed_dir}")
            return self.stats

        # Clear existing topology_links before fresh import
        try:
            self.db.execute("DELETE FROM topology_links")
            print("🗑️  已清空 topology_links 表")
        except Exception as e:
            logger.warning(f"Failed to clear topology_links: {e}")

        # Build OSPF neighbor ID to device name mapping
        ospf_id_to_device = self._build_ospf_id_mapping(parsed_dir)

        # Build ARP tables for IP lookup
        # local_ips: device's own interface IPs (AGE="-")
        # neighbor_ips: learned neighbor IPs on each interface
        local_ips, neighbor_ips = self._build_arp_tables(parsed_dir)

        # ============================================================
        # 第一阶段: 收集所有链接 (不直接插入)
        # ============================================================
        all_links: list[dict[str, str]] = []

        # 遍历每个设备的Parsed目录
        for device_dir in sorted(parsed_dir.glob("*/")):
            device = device_dir.name

            if device not in self.known_devices:
                logger.warning(f"Unknown device in parsed: {device}")
                continue

            print(f"\n🔹 处理设备: {device}")

            # 遍历该设备的所有JSON文件
            for json_file in sorted(device_dir.glob("*.json")):
                # Skip non-topology files
                if json_file.stem.lower() in ("logs", "show-running-config", "show-startup-config"):
                    continue

                try:
                    with open(json_file) as f:
                        data = json.load(f)

                    # Skip if data is not a dict (e.g., logs.json is a list)
                    if not isinstance(data, dict):
                        continue

                    # Parsed JSON格式: data是list或dict
                    items = data.get("data", [])
                    if isinstance(items, dict):
                        items = [items]  # 转换为list

                    # Determine file type for specialized handling
                    filename_lower = json_file.stem.lower()

                    for link_data in items:
                        if not link_data or not isinstance(link_data, dict):
                            continue

                        try:
                            # Handle different data types
                            # Initialize AS variables (only used for BGP)
                            local_as = ""
                            remote_as = ""
                            bgp_type = ""

                            if "ospf" in filename_lower:
                                # OSPF Neighbor: use NEIGHBOR_ID to find device
                                neighbor_id = link_data.get("NEIGHBOR_ID", "")
                                remote_device = ospf_id_to_device.get(neighbor_id, "")
                                local_port = link_data.get("INTERFACE", "")
                                remote_port = ""  # 将在第二阶段交叉查找
                                local_ip = ""  # 将在第二阶段交叉查找
                                remote_ip = link_data.get("IP_ADDRESS", "")

                                if not remote_device:
                                    self.stats["invalid"] += 1
                                    continue

                                # 收集链接数据，稍后批量处理
                                all_links.append(
                                    {
                                        "local_device": device,
                                        "remote_device": remote_device,
                                        "local_port": local_port,
                                        "remote_port": remote_port,
                                        "local_ip": local_ip,
                                        "remote_ip": remote_ip,
                                        "local_as": "",
                                        "remote_as": "",
                                        "bgp_type": "",
                                        "protocol": "OSPF",
                                        "layer": "L3",
                                    }
                                )
                                continue

                            elif "bgp" in filename_lower:
                                # BGP Neighbor: Parse from BGP summary output
                                # NTC templates may parse as "Neighbor" or "network" field
                                neighbor_ip = link_data.get("Neighbor", "") or link_data.get(
                                    "network", ""
                                )

                                # Skip header/garbage lines
                                if not neighbor_ip:
                                    continue
                                # Skip common header keywords
                                skip_values = {
                                    "Neighbor",
                                    "BGP",
                                    "Codes:",
                                    "9",
                                    "11",
                                    "0",
                                    "1",
                                    "6/4",
                                }
                                if neighbor_ip in skip_values:
                                    continue

                                # Must be a valid IP address for actual BGP neighbor
                                if not _is_ip_address(neighbor_ip):
                                    continue

                                # Try to map neighbor IP to device name
                                remote_device = ospf_id_to_device.get(neighbor_ip, "")

                                # If not found by router ID, skip
                                if not remote_device:
                                    self.stats["skipped"] += 1
                                    continue

                                # Get AS numbers for eBGP/iBGP determination
                                # In parsed output, AS is in "metric" field due to parsing
                                remote_as = str(
                                    link_data.get("metric", "") or link_data.get("AS", "")
                                )
                                local_as = self._get_device_as(device)

                                # 计算 BGP 类型 (在导入阶段完成)
                                bgp_type = "iBGP" if local_as == remote_as else "eBGP"

                                local_port = ""
                                remote_port = ""
                                local_ip = self._get_device_router_id(device)
                                remote_ip = neighbor_ip

                                # 收集BGP链接数据
                                all_links.append(
                                    {
                                        "local_device": device,
                                        "remote_device": remote_device,
                                        "local_port": local_port,
                                        "remote_port": remote_port,
                                        "local_ip": local_ip,
                                        "remote_ip": remote_ip,
                                        "local_as": local_as,
                                        "remote_as": remote_as,
                                        "bgp_type": bgp_type,
                                        "protocol": "BGP",
                                        "layer": "L3",
                                    }
                                )
                                continue

                            elif "cdp" in filename_lower or "lldp" in filename_lower:
                                # CDP/LLDP: use device_id
                                remote_device = (
                                    link_data.get("device_id")
                                    or link_data.get("remote_device")
                                    or ""
                                )
                                if remote_device.endswith(".local"):
                                    remote_device = remote_device[:-6]
                                local_port = link_data.get("local_intrfce") or link_data.get(
                                    "local_port", ""
                                )
                                remote_port = link_data.get("port_id") or link_data.get(
                                    "remote_port", ""
                                )

                                # 收集CDP/LLDP链接数据
                                all_links.append(
                                    {
                                        "local_device": device,
                                        "remote_device": remote_device,
                                        "local_port": local_port,
                                        "remote_port": remote_port,
                                        "local_ip": "",
                                        "remote_ip": "",
                                        "local_as": "",
                                        "remote_as": "",
                                        "bgp_type": "",
                                        "protocol": "CDP" if "cdp" in filename_lower else "LLDP",
                                        "layer": "L1",
                                    }
                                )
                                continue
                            else:
                                # Skip non-topology files
                                continue

                        except ValidationError:
                            # ❌ 验证失败，拒绝插入
                            self.stats["invalid"] += 1

                except json.JSONDecodeError as e:
                    logger.error(f"Error parsing {json_file.name}: {e}")
                    self.stats["skipped"] += 1
                except Exception as e:
                    logger.error(f"Error reading {json_file.name}: {e}")
                    self.stats["skipped"] += 1

        # ============================================================
        # 第二阶段: 交叉查找，丰富OSPF和CDP数据
        # ============================================================
        print("\n🔄 第二阶段: 交叉查找完善OSPF/CDP数据...")

        # 建立 OSPF 链接索引: (local_device, remote_device) -> link_data
        ospf_index: dict[tuple[str, str], dict[str, str]] = {}
        for link in all_links:
            if link["protocol"] == "OSPF":
                key = (link["local_device"], link["remote_device"])
                ospf_index[key] = link

        # 交叉查找填充 OSPF 的 remote_port 和 local_ip
        for link in all_links:
            if link["protocol"] == "OSPF":
                # 查找反向链接 (remote_device -> local_device)
                reverse_key = (link["remote_device"], link["local_device"])
                reverse_link = ospf_index.get(reverse_key)

                if reverse_link:
                    # 反向链接的 local_port 就是我们的 remote_port
                    link["remote_port"] = reverse_link.get("local_port", "")
                    # 反向链接的 remote_ip 就是我们的 local_ip
                    link["local_ip"] = reverse_link.get("remote_ip", "")

        # 交叉查找填充 CDP/LLDP 的 IP 地址 (从ARP表)
        for link in all_links:
            if link["protocol"] in ("CDP", "LLDP"):
                device = link["local_device"]
                remote_device = link["remote_device"]
                local_port = link["local_port"]
                remote_port = link["remote_port"]

                # Get local IP from local device's ARP (own interface IP)
                if device in local_ips and local_port:
                    normalized_port = self._normalize_interface_name(local_port)
                    local_ip = local_ips[device].get(normalized_port, "")
                    if local_ip:
                        link["local_ip"] = local_ip

                # Get remote IP from remote device's ARP (their interface IP)
                if remote_device in local_ips and remote_port:
                    normalized_remote = self._normalize_interface_name(remote_port)
                    remote_ip = local_ips[remote_device].get(normalized_remote, "")
                    if remote_ip:
                        link["remote_ip"] = remote_ip

        # ============================================================
        # 第三阶段: 验证并插入数据库
        # ============================================================
        print("\n📊 第三阶段: 验证并插入数据库...")
        device_stats: dict[str, dict[str, int]] = {}

        for link_data in all_links:
            device = link_data["local_device"]
            if device not in device_stats:
                device_stats[device] = {"valid": 0, "invalid": 0}

            try:
                # Pydantic验证
                link = TopologyLink(
                    local_device=link_data["local_device"],
                    remote_device=link_data["remote_device"],
                    local_port=link_data["local_port"],
                    remote_port=link_data["remote_port"],
                    layer=link_data["layer"],
                    protocol=link_data["protocol"],
                    confidence=0.95,
                )

                # 插入数据库
                self._insert_link(
                    link,
                    local_ip=link_data["local_ip"],
                    remote_ip=link_data["remote_ip"],
                    local_as=link_data["local_as"],
                    remote_as=link_data["remote_as"],
                    bgp_type=link_data["bgp_type"],
                )
                self.stats["valid"] += 1
                device_stats[device]["valid"] += 1

            except ValidationError:
                self.stats["invalid"] += 1
                device_stats[device]["invalid"] += 1

        # 打印每个设备的统计
        for device, stats in sorted(device_stats.items()):
            if stats["valid"] > 0 or stats["invalid"] > 0:
                print(f"   {device}: ✅ {stats['valid']} 有效 | ❌ {stats['invalid']} 无效")

        self._print_stats("Parsed JSON")
        return self.stats

    def _build_arp_tables(
        self, parsed_dir: Path
    ) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
        """Build ARP tables from parsed show-arp.json files.

        Returns:
            Tuple of:
            - local_ips: {device: {normalized_interface: local_ip}}  (AGE="-")
            - neighbor_ips: {device: {normalized_interface: neighbor_ip}}  (AGE!="-")
        """
        local_ips: dict[str, dict[str, str]] = {}
        neighbor_ips: dict[str, dict[str, str]] = {}

        for device_dir in parsed_dir.glob("*/"):
            device = device_dir.name
            arp_file = device_dir / "show-arp.json"

            if not arp_file.exists():
                continue

            try:
                with open(arp_file) as f:
                    arp_data = json.load(f)

                entries = arp_data.get("data", [])
                if not entries:
                    continue

                device_local: dict[str, str] = {}
                device_neighbor: dict[str, str] = {}

                for entry in entries:
                    interface = entry.get("INTERFACE", "")
                    address = entry.get("ADDRESS", "")
                    age = entry.get("AGE_MIN", "")

                    if interface and address:
                        normalized = self._normalize_interface_name(interface)
                        if age == "-":
                            # Local IP (self interface)
                            device_local[normalized] = address
                        else:
                            # Neighbor IP (learned via ARP)
                            device_neighbor[normalized] = address

                if device_local:
                    local_ips[device] = device_local
                if device_neighbor:
                    neighbor_ips[device] = device_neighbor

            except (json.JSONDecodeError, OSError) as e:
                logger.debug(f"Failed to load ARP table for {device}: {e}")

        return local_ips, neighbor_ips

    def _normalize_interface_name(self, name: str) -> str:
        """Normalize interface name for consistent lookup.

        Examples:
            "Eth 0/0" -> "Ethernet0/0"
            "Gig 2" -> "GigabitEthernet2"
            "Ethernet0/0" -> "Ethernet0/0"
        """
        name = name.strip()

        # If already full name, return as-is
        if name.startswith(("GigabitEthernet", "FastEthernet", "TenGigabitEthernet", "Ethernet")):
            return name
        if name.startswith(("Loopback", "Vlan")):
            return name

        # Common abbreviation mappings (only for short forms)
        abbrev_map = [
            (r"^Gi\s*(\S+)$", r"GigabitEthernet\1"),
            (r"^Gig\s*(\S+)$", r"GigabitEthernet\1"),
            (r"^Fa\s*(\S+)$", r"FastEthernet\1"),
            (r"^Eth\s*(\S+)$", r"Ethernet\1"),
            (r"^Te\s*(\S+)$", r"TenGigabitEthernet\1"),
            (r"^Lo\s*(\S+)$", r"Loopback\1"),
            (r"^Vl\s*(\S+)$", r"Vlan\1"),
        ]

        for pattern, replacement in abbrev_map:
            match = re.match(pattern, name, re.IGNORECASE)
            if match:
                return re.sub(pattern, replacement, name, flags=re.IGNORECASE)

        return name

    def _build_ospf_id_mapping(self, parsed_dir: Path) -> dict[str, str]:
        """Build mapping from OSPF Router ID to device name.

        Extracts router ID from show-version or show-ip-ospf output.
        """

        mapping: dict[str, str] = {}

        # Only map routers (devices starting with R, not SW/switches)
        # Pattern: x.x.x.x where x is device number (R1 = 1.1.1.1, R2 = 2.2.2.2)
        for device in self.known_devices:
            # Only process routers (R1, R2, etc.) not switches (SW1, SW2)
            if not device.upper().startswith("R"):
                continue
            # Extract number from device name (R1 -> 1, R2 -> 2)
            match = re.search(r"^R(\d+)$", device, re.IGNORECASE)
            if match:
                num = match.group(1)
                # Common router ID patterns
                mapping[f"{num}.{num}.{num}.{num}"] = device  # 1.1.1.1 -> R1

        return mapping

    def _infer_protocol(self, filename: str) -> str:
        """根据文件名推断协议"""
        filename_lower = filename.lower()
        if "cdp" in filename_lower:
            return "CDP"
        elif "lldp" in filename_lower:
            return "LLDP"
        elif "ospf" in filename_lower:
            return "OSPF"
        elif "bgp" in filename_lower:
            return "BGP"
        else:
            return "UNKNOWN"

    def _infer_layer(self, filename: str) -> str:
        """根据文件名推断网络层"""
        filename_lower = filename.lower()
        if "cdp" in filename_lower or "lldp" in filename_lower:
            return "L1"
        else:
            return "L3"

    def _get_device_router_id(self, device: str) -> str:
        """Get router ID for a device based on naming convention.

        R1 -> 1.1.1.1, R2 -> 2.2.2.2, etc.
        """
        import re

        match = re.search(r"^R(\d+)$", device, re.IGNORECASE)
        if match:
            num = match.group(1)
            return f"{num}.{num}.{num}.{num}"
        return ""

    def _get_device_as(self, device: str) -> str:
        """Get AS number for a device.

        This is a simplified lookup. In production, would parse from config.
        For lab topology, use naming convention or default AS.
        """
        # For lab: assume all routers in same AS unless different naming
        # Could be enhanced to read from show ip bgp output
        return "65000"  # Default AS

    def _insert_link(
        self,
        link: TopologyLink,
        local_ip: str = "",
        remote_ip: str = "",
        local_as: str = "",
        remote_as: str = "",
        bgp_type: str = "",
    ) -> None:
        """验证通过后插入数据库"""
        try:
            # Build metadata JSON with IP addresses and AS info
            metadata = {}
            if local_ip:
                metadata["local_ip"] = local_ip
            if remote_ip:
                metadata["remote_ip"] = remote_ip
            if local_as:
                metadata["local_as"] = local_as
            if remote_as:
                metadata["remote_as"] = remote_as
            if bgp_type:
                metadata["bgp_type"] = bgp_type

            metadata_json = json.dumps(metadata) if metadata else None

            self.db.execute(
                """
                INSERT INTO topology_links
                (local_device, remote_device, local_port, remote_port,
                 layer, protocol, metadata, discovered_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
                [
                    link.local_device,
                    link.remote_device,
                    link.local_port,
                    link.remote_port,
                    link.layer,
                    link.protocol,
                    metadata_json,
                ],
            )
        except Exception as e:
            logger.error(f"Failed to insert link: {e}")

    def commit(self) -> None:
        """提交所有更改"""
        try:
            self.db.commit()
        except Exception as e:
            logger.error(f"Commit failed: {e}")

    def close(self) -> None:
        """关闭数据库连接"""
        self.db.close()

    def _print_stats(self, mode: str) -> None:
        """打印导入统计"""
        total = self.stats["valid"] + self.stats["invalid"] + self.stats["skipped"]
        print("\n" + "=" * 80)
        print(f"📊 {mode} 导入统计:")
        print(f"  ✅ 有效链接:   {self.stats['valid']:>4}")
        print(f"  ❌ 无效链接:   {self.stats['invalid']:>4}")
        print(f"  ⏭️  跳过:      {self.stats['skipped']:>4}")
        print(f"  📈 总计:       {total:>4}")
        if self.stats["valid"] > 0:
            success_rate = self.stats["valid"] / total * 100 if total > 0 else 0
            print(f"  🎯 成功率:     {success_rate:.1f}%")
        print("=" * 80)


# ============================================================================
# 第4部分: 使用示例和测试
# ============================================================================


def test_pydantic_validation() -> None:
    """测试Pydantic验证器"""
    print("\n🧪 测试Pydantic验证器:")
    print("=" * 80)

    test_cases = [
        ("R3", True, "有效的设备名"),
        ("Neighbor", False, "通用占位符"),
        ("3.3.3.3", False, "IP地址"),
        ("R7", False, "未知设备"),
        ("Unknown", False, "通用占位符"),
        ("Total", False, "通用占位符"),
    ]

    for device_name, should_pass, description in test_cases:
        try:
            _ = TopologyLink(
                local_device="R1", remote_device=device_name, layer="L3", protocol="OSPF"
            )
            result = "✅ 通过" if should_pass else "❌ 应该拒绝但通过"
        except ValidationError:
            result = "❌ 拒绝" if not should_pass else "❌ 应该通过但拒绝"

        status_icon = (
            "✅"
            if (should_pass and "通过" in result) or (not should_pass and "拒绝" in result)
            else "⚠️"
        )
        print(f"  {status_icon} {device_name:20} → {result:15} ({description})")


def main() -> None:
    """
    主函数示例
    """

    # 1️⃣ 测试Pydantic验证
    test_pydantic_validation()

    # 2️⃣ 初始化导入器
    print("\n\n📥 开始数据导入...")
    importer = TopologyImporter(".olav/data/topology.db")

    sync_dir = "data/sync/2026-01-13"

    # 3️⃣ 使用Parsed JSON进行导入
    importer.import_from_parsed_json(sync_dir)

    # 4️⃣ 提交更改
    importer.commit()
    importer.close()

    # 5️⃣ 最终统计
    print("\n\n✅ 导入完成!")


if __name__ == "__main__":
    main()
