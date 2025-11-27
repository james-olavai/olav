#!/usr/bin/env python3
"""Analyze eBGP neighbor failure between R1 and R2."""

import pandas as pd

def main():
    print("=" * 60)
    print("eBGP Neighbor Analysis: R1 (AS 65000) <-> R2 (AS 65001)")
    print("=" * 60)

    # 1. BGP Neighbor Status
    print("\n=== 1. BGP Neighbor Status ===")
    bgp = pd.read_parquet('data/suzieq-parquet/bgp')
    
    # Find eBGP peering (different AS)
    ebgp = bgp[(bgp['hostname'].isin(['R1', 'R2'])) & (bgp['asn'] != bgp['peerAsn'])]
    for _, row in ebgp.drop_duplicates(subset=['hostname', 'peer']).iterrows():
        print(f"  {row['hostname']} -> {row['peer']} (AS {row['peerAsn']}): {row['state']}")
        if row.get('updateSource'):
            print(f"    Update Source: {row['updateSource']}")
        if row.get('reason'):
            print(f"    Reason: {row['reason']}")
    
    # 2. Interface Status on R1 and R2
    print("\n=== 2. Interface Status (R1/R2) ===")
    intf = pd.read_parquet('data/suzieq-parquet/interfaces')
    r1r2_intf = intf[intf['hostname'].isin(['R1', 'R2'])]
    
    for hostname in ['R1', 'R2']:
        print(f"\n  {hostname}:")
        host_intf = r1r2_intf[r1r2_intf['hostname'] == hostname]
        for _, row in host_intf.iterrows():
            ip_list = row.get('ipAddressList', [])
            if isinstance(ip_list, list) and len(ip_list) > 0:
                ip_str = ', '.join(ip_list)
                print(f"    {row['ifname']}: state={row['state']}, admin={row['adminState']}, ip={ip_str}")
    
    # 3. Check routing to peer
    print("\n=== 3. Routes to 10.1.12.0/24 ===")
    routes = pd.read_parquet('data/suzieq-parquet/routes')
    r1r2_routes = routes[routes['hostname'].isin(['R1', 'R2'])]
    
    for hostname in ['R1', 'R2']:
        print(f"\n  {hostname}:")
        host_routes = r1r2_routes[r1r2_routes['hostname'] == hostname]
        for _, row in host_routes.iterrows():
            prefix = str(row.get('prefix', ''))
            if '10.1.12' in prefix:
                nexthop = row.get('nexthopIps', [])
                oif = row.get('oifs', [])
                proto = row.get('protocol', '')
                print(f"    {prefix} via {nexthop} out {oif} ({proto})")
    
    # 4. ARP/ND entries for 10.1.12.x
    print("\n=== 4. ARP Entries for 10.1.12.x ===")
    try:
        arpnd = pd.read_parquet('data/suzieq-parquet/arpnd')
        r1r2_arp = arpnd[arpnd['hostname'].isin(['R1', 'R2'])]
        
        for hostname in ['R1', 'R2']:
            host_arp = r1r2_arp[r1r2_arp['hostname'] == hostname]
            found = False
            for _, row in host_arp.iterrows():
                ip = str(row.get('ipAddress', ''))
                if '10.1.12' in ip:
                    mac = row.get('macaddr', '')
                    oif = row.get('oif', '')
                    print(f"  {hostname}: {ip} -> {mac} on {oif}")
                    found = True
            if not found:
                print(f"  {hostname}: No ARP entries for 10.1.12.x - Layer 2 issue?")
    except Exception as e:
        print(f"  Error reading ARP data: {e}")
    
    # 5. Device config analysis
    print("\n=== 5. BGP Configuration ===")
    devconfig = pd.read_parquet('data/suzieq-parquet/devconfig')
    r1r2_config = devconfig[devconfig['hostname'].isin(['R1', 'R2'])]
    
    for hostname in ['R1', 'R2']:
        print(f"\n  {hostname} BGP Config:")
        host_cfg = r1r2_config[r1r2_config['hostname'] == hostname]
        for _, row in host_cfg.iterrows():
            config = row.get('config', '')
            if config:
                lines = config.split('\n')
                in_bgp = False
                for line in lines:
                    if 'router bgp' in line:
                        in_bgp = True
                    if in_bgp:
                        print(f"    {line}")
                        if line.strip() == '!' or (line.strip() and not line.startswith(' ') and 'router bgp' not in line):
                            in_bgp = False
                break
    
    # Summary
    print("\n" + "=" * 60)
    print("DIAGNOSIS SUMMARY")
    print("=" * 60)
    
    issues = []
    
    # Check eBGP specific issues
    r1_ebgp = ebgp[ebgp['hostname'] == 'R1'].drop_duplicates(subset=['hostname', 'peer'])
    r2_ebgp = ebgp[ebgp['hostname'] == 'R2'].drop_duplicates(subset=['hostname', 'peer'])
    
    # Check update-source
    if len(r1_ebgp) > 0:
        src = r1_ebgp.iloc[0].get('updateSource', '')
        if not src:
            issues.append("R1: No update-source for eBGP - may need if using loopback")
    
    if len(r2_ebgp) > 0:
        src = r2_ebgp.iloc[0].get('updateSource', '')
        if not src:
            issues.append("R2: No update-source for eBGP - may need if using loopback")
    
    # Check if interfaces have IPs in 10.1.12.x range
    r1_has_link = False
    r2_has_link = False
    for _, row in r1r2_intf.iterrows():
        ips = row.get('ipAddressList', [])
        if isinstance(ips, list):
            for ip in ips:
                if '10.1.12.1' in ip:
                    r1_has_link = True
                if '10.1.12.2' in ip:
                    r2_has_link = True
    
    if not r1_has_link:
        issues.append("R1: No interface with IP 10.1.12.1 - missing link to R2!")
    if not r2_has_link:
        issues.append("R2: No interface with IP 10.1.12.2 - missing link to R1!")
    
    if issues:
        print("\n⚠️  Issues Found:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("\n✅ No obvious configuration issues. Check:")
        print("  - TCP port 179 connectivity (telnet 10.1.12.x 179)")
        print("  - Firewall/ACL rules blocking BGP")
        print("  - MD5 authentication mismatch")
        print("  - ebgp-multihop if not directly connected")

if __name__ == "__main__":
    main()
