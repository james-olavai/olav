# CAB Validation Report — r1-r4-ebgp-v2

## Summary: FAIL

BGP sessions failed to establish on both nodes (state=active). Interfaces up with correct IPs, but no TCP connection for BGP peering.

## Evidence (per node)

### r1:
**Interface:**
```
ethernet-1/1 is up, speed 25G, type None
  ethernet-1/1.0 is up
    IPv4 addr    : 172.16.14.1/30 (static, preferred, primary)
```

**BGP Neighbor:**
```
| default              | 172.16.14.2                    | ebgp-r4              | S      | 65001      | active           | -                |                |                                |
Summary:
1 configured neighbors, 0 configured sessions are established
```

**Routes:**
```
2 received BGP routes: 2 used, 2 valid, 0 stale
| u*>    | 1.1.1.1/32           | 0.0.0.0                        |        |        |  i                                                           |
| u*>    | 172.16.14.0/30       | 0.0.0.0                        |        |        |  i                                                           |
```
(No peer loopback 4.4.4.4/32 received)

### r4:
**Interface:**
```
ethernet-1/1 is up, speed 25G, type None
  ethernet-1/1.0 is up
    IPv4 addr    : 172.16.14.2/30 (static, preferred, primary)
```

**BGP Neighbor:**
```
| default              | 172.16.14.1                    | ebgp-r1              | S      | 65000      | active           | -                |                |                                |
Summary:
1 configured neighbors, 0 configured sessions are established
```

**Routes:**
```
2 received BGP routes: 2 used, 2 valid, 0 stale
| u*>    | 4.4.4.4/32           | 0.0.0.0                        |        |        |  i                                                           |
| u*>    | 172.16.14.0/30       | 0.0.0.0                        |        |        |  i                                                           |
```
(No peer loopback 1.1.1.1/32 received)

## Interpretation (per criterion)
- **Interfaces:** PASS - Up on both nodes with correct IPs (172.16.14.1/30 r1, .2/30 r4)
- **BGP Neighbor State:** FAIL - 'active' on both (TCP connection failure to peer IP). Not 'Established'.
- **Peer AS:** PASS - Correct (r1 sees 65001, r4 sees 65000)
- **Routes:** FAIL - No received routes from peer (only local loopback + connected). Expected rx_count >=1 (peer /32)

**Diagnostic hint:** BGP state=active → TCP not reaching peer. Check: IP reachability (ping?), firewall, MTU mismatch, TTL (eBGP multihop?), interface MTU.