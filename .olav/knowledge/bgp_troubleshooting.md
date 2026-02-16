# BGP Troubleshooting Guide

## BGP Neighbor Down

When a BGP neighbor goes down, follow these steps:

1. Check if the neighbor is reachable: `ping <neighbor-ip>`
2. Verify BGP configuration: `show run | include neighbor`
3. Check BGP status: `show ip bgp summary`

Common causes:
- Interface down
- BGP configuration mismatch
- ACL blocking traffic
- Authentication failure
