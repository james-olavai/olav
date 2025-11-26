#!/usr/bin/env python3
"""
测试设备是否支持 OpenConfig

用途: 验证网络设备的 NETCONF/OpenConfig 支持情况
日期: 2025-11-21
"""

import sys
import asyncio
from pathlib import Path

# Windows 平台事件循环修复
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ncclient import manager
from ncclient.operations import RPCError
from ncclient.transport.errors import SSHError, AuthenticationError
import xml.etree.ElementTree as ET


def print_section(title: str):
    """打印分隔线"""
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


def test_netconf_connection(host: str, port: int, username: str, password: str):
    """测试 NETCONF 连接"""
    print_section("1. 测试 NETCONF 连接")
    
    print(f"设备地址: {host}:{port}")
    print(f"用户名: {username}")
    print(f"密码: {'*' * len(password)}")
    
    try:
        # 尝试连接
        print("\n正在连接...")
        
        conn = manager.connect(
            host=host,
            port=port,
            username=username,
            password=password,
            hostkey_verify=False,
            device_params={'name': 'default'},  # 尝试通用设备类型
            timeout=30,
            allow_agent=False,
            look_for_keys=False
        )
        
        print("✅ NETCONF 连接成功!")
        return conn
        
    except AuthenticationError as e:
        print(f"❌ 认证失败: {e}")
        print("   请检查用户名和密码是否正确")
        return None
    except SSHError as e:
        print(f"❌ SSH 连接失败: {e}")
        print("   可能原因:")
        print("   - 设备未启用 NETCONF")
        print("   - 端口号错误 (通常是 830)")
        print("   - 网络不可达")
        return None
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        return None


def check_capabilities(conn):
    """检查设备支持的 Capabilities"""
    print_section("2. 检查 NETCONF Capabilities")
    
    capabilities = conn.server_capabilities
    
    print(f"设备支持 {len(capabilities)} 个 Capabilities:\n")
    
    # 重要的 capabilities 分类
    important_caps = {
        'base': [],
        'openconfig': [],
        'ietf': [],
        'cisco': [],
        'other': []
    }
    
    for cap in capabilities:
        cap_str = str(cap)
        
        # 分类
        if 'netconf/base' in cap_str:
            important_caps['base'].append(cap_str)
        elif 'openconfig' in cap_str.lower():
            important_caps['openconfig'].append(cap_str)
        elif 'ietf' in cap_str:
            important_caps['ietf'].append(cap_str)
        elif 'cisco' in cap_str:
            important_caps['cisco'].append(cap_str)
        else:
            important_caps['other'].append(cap_str)
    
    # 打印分类结果
    print("📋 NETCONF Base:")
    if important_caps['base']:
        for cap in important_caps['base']:
            print(f"   ✓ {cap}")
    else:
        print("   (无)")
    
    print("\n🌟 OpenConfig Models:")
    if important_caps['openconfig']:
        for cap in important_caps['openconfig']:
            print(f"   ✓ {cap}")
    else:
        print("   ❌ 未发现 OpenConfig 支持")
    
    print("\n📚 IETF Models:")
    if important_caps['ietf']:
        for cap in important_caps['ietf'][:5]:  # 只显示前5个
            print(f"   ✓ {cap}")
        if len(important_caps['ietf']) > 5:
            print(f"   ... 还有 {len(important_caps['ietf']) - 5} 个")
    else:
        print("   (无)")
    
    print("\n🔧 厂商特定 Models:")
    if important_caps['cisco']:
        for cap in important_caps['cisco'][:5]:
            print(f"   ✓ {cap}")
        if len(important_caps['cisco']) > 5:
            print(f"   ... 还有 {len(important_caps['cisco']) - 5} 个")
    else:
        print("   (无)")
    
    return important_caps


def test_get_config(conn):
    """测试 get-config 操作"""
    print_section("3. 测试 get-config 操作")
    
    try:
        print("正在获取 running-config (只获取接口部分)...")
        
        # 使用过滤器只获取接口配置
        filter_xml = """
        <filter>
            <interfaces xmlns="urn:ietf:params:xml:ns:yang:ietf-interfaces"/>
        </filter>
        """
        
        config = conn.get_config(source='running', filter=('subtree', filter_xml))
        
        print("✅ get-config 成功!")
        print(f"\n返回数据长度: {len(str(config))} 字符")
        
        # 尝试解析 XML
        try:
            root = ET.fromstring(str(config))
            print(f"✅ XML 解析成功")
            
            # 查找接口
            namespaces = {
                'nc': 'urn:ietf:params:xml:ns:netconf:base:1.0',
                'if': 'urn:ietf:params:xml:ns:yang:ietf-interfaces'
            }
            
            interfaces = root.findall('.//if:interface', namespaces)
            if interfaces:
                print(f"\n发现 {len(interfaces)} 个接口:")
                for i, intf in enumerate(interfaces[:3], 1):  # 只显示前3个
                    name = intf.find('if:name', namespaces)
                    if name is not None:
                        print(f"   {i}. {name.text}")
                if len(interfaces) > 3:
                    print(f"   ... 还有 {len(interfaces) - 3} 个接口")
            else:
                print("\n⚠️  未找到接口信息 (可能使用了不同的 YANG 模型)")
                
        except Exception as e:
            print(f"⚠️  XML 解析警告: {e}")
        
        return True
        
    except RPCError as e:
        print(f"❌ RPC 错误: {e}")
        return False
    except Exception as e:
        print(f"❌ 操作失败: {e}")
        return False


def test_openconfig_get(conn):
    """测试 OpenConfig 数据获取"""
    print_section("4. 测试 OpenConfig 数据获取")
    
    # 尝试获取 OpenConfig 接口配置
    openconfig_filters = [
        # OpenConfig 接口模型
        {
            'name': 'OpenConfig Interfaces',
            'filter': """
            <filter>
                <interfaces xmlns="http://openconfig.net/yang/interfaces"/>
            </filter>
            """
        },
        # OpenConfig 网络实例
        {
            'name': 'OpenConfig Network Instances',
            'filter': """
            <filter>
                <network-instances xmlns="http://openconfig.net/yang/network-instance"/>
            </filter>
            """
        },
        # OpenConfig BGP
        {
            'name': 'OpenConfig BGP',
            'filter': """
            <filter>
                <bgp xmlns="http://openconfig.net/yang/bgp"/>
            </filter>
            """
        }
    ]
    
    success_count = 0
    
    for test in openconfig_filters:
        print(f"\n尝试获取 {test['name']}...")
        
        try:
            result = conn.get(filter=('subtree', test['filter']))
            
            print(f"   ✅ 成功! (返回 {len(str(result))} 字符)")
            success_count += 1
            
            # 尝试解析第一个成功的结果
            if success_count == 1:
                try:
                    root = ET.fromstring(str(result))
                    print(f"   ✅ XML 格式正确")
                except Exception as e:
                    print(f"   ⚠️  XML 解析警告: {e}")
            
        except RPCError as e:
            print(f"   ❌ 不支持: {e}")
        except Exception as e:
            print(f"   ❌ 错误: {e}")
    
    print(f"\n{'='*70}")
    if success_count > 0:
        print(f"✅ OpenConfig 支持测试: {success_count}/{len(openconfig_filters)} 通过")
        print("   设备支持 OpenConfig!")
    else:
        print(f"❌ OpenConfig 支持测试: 0/{len(openconfig_filters)} 通过")
        print("   设备可能不支持 OpenConfig，或需要额外配置")
    
    return success_count > 0


def generate_report(host: str, has_netconf: bool, capabilities: dict, has_openconfig: bool):
    """生成测试报告"""
    print_section("测试报告总结")
    
    print(f"设备地址: {host}")
    print(f"\n测试结果:")
    print(f"  NETCONF 连接:    {'✅ 支持' if has_netconf else '❌ 不支持'}")
    
    if has_netconf:
        openconfig_count = len(capabilities.get('openconfig', []))
        print(f"  OpenConfig Models: {openconfig_count} 个")
        print(f"  OpenConfig 数据:  {'✅ 支持' if has_openconfig else '❌ 不支持'}")
        
        print(f"\n推荐配置:")
        if has_openconfig:
            print(f"  ✅ 可以使用 NETCONF + OpenConfig 管理此设备")
            print(f"  ✅ 建议在 inventory.csv 中配置:")
            print(f"     platform: openconfig")
            print(f"     protocol: netconf")
        else:
            print(f"  ⚠️  设备支持 NETCONF 但 OpenConfig 支持有限")
            print(f"  ⚠️  建议:")
            print(f"     1. 检查设备 IOS 版本是否支持 OpenConfig")
            print(f"     2. 或使用厂商特定的 YANG 模型")
            print(f"     3. 或降级使用 CLI 方式管理")
    else:
        print(f"  ❌ 设备不支持 NETCONF")
        print(f"  ❌ 建议使用 CLI 方式管理此设备")
    
    print(f"\n{'='*70}\n")


def main():
    """主函数"""
    # 设备配置
    DEVICE_HOST = "192.168.100.109"
    DEVICE_PORT = 830  # NETCONF 默认端口
    USERNAME = "cisco"
    PASSWORD = "cisco"
    
    print(f"""
╔═══════════════════════════════════════════════════════════════════╗
║                                                                   ║
║           OLAV - OpenConfig 支持测试工具                          ║
║                                                                   ║
╚═══════════════════════════════════════════════════════════════════╝
    """)
    
    # 1. 测试 NETCONF 连接
    conn = test_netconf_connection(DEVICE_HOST, DEVICE_PORT, USERNAME, PASSWORD)
    
    if not conn:
        print("\n❌ 无法建立 NETCONF 连接，测试终止")
        print("\n可能的解决方案:")
        print("  1. 在设备上启用 NETCONF:")
        print("     Router(config)# netconf-yang")
        print("     Router(config)# netconf-yang cisco-odm polling-enable")
        print("  2. 检查设备是否可达:")
        print(f"     ping {DEVICE_HOST}")
        print("  3. 验证端口是否正确:")
        print(f"     telnet {DEVICE_HOST} {DEVICE_PORT}")
        return 1
    
    try:
        # 2. 检查 Capabilities
        capabilities = check_capabilities(conn)
        
        # 3. 测试基本操作
        get_config_ok = test_get_config(conn)
        
        # 4. 测试 OpenConfig
        has_openconfig = False
        if capabilities.get('openconfig'):
            has_openconfig = test_openconfig_get(conn)
        else:
            print_section("4. 测试 OpenConfig 数据获取")
            print("⚠️  设备 Capabilities 中未发现 OpenConfig 模型")
            print("   跳过 OpenConfig 数据测试")
        
        # 5. 生成报告
        generate_report(
            DEVICE_HOST,
            has_netconf=True,
            capabilities=capabilities,
            has_openconfig=has_openconfig
        )
        
        return 0
        
    except Exception as e:
        print(f"\n❌ 测试过程出错: {e}")
        import traceback
        traceback.print_exc()
        return 1
        
    finally:
        if conn:
            print("正在关闭连接...")
            conn.close_session()
            print("✅ 连接已关闭")


if __name__ == "__main__":
    sys.exit(main())
