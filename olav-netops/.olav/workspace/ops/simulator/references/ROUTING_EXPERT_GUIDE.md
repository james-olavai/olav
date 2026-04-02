# 🕵️‍♂️ Routing Expert Troubleshooting Guide

This guide helps you analyze BGP and OSPF states mathematically and procedurally.

## 1. BGP Neighbor States
- **`Idle`**: Check local config and physical liveness.
- **`Active`**: BGP is trying to connect. Likely an **MTU mismatch**, **ACL blocking TCP 179**, or **Missing Route** to peer.
- **`Established`**: Peer is up.

## 2. BGP Path Selection (Priority Order)
1. **Weight** (Highest wins)
2. **Local Preference** (Highest wins)
3. **Locally Originated**
4. **AS Path** (Shortest wins)
5. **Origin Type** (IGP > EGP > Incomplete)
6. **MED** (Lowest wins)

## 💡 Troubleshooting Logic
- **Missing Route?** Run `traceroute` from source device to peer IP.
- **Path Shift?** Use the `diff` specialist to compare `as_path` between current and previous `snapshot_id`.
- **Latency/Flapping?** Check interface `input_errors` and `output_errors` in the `interfaces` table.
