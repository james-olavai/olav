# Built-in recipes (ship with olav-netops)

These are automatically loaded into `view_recipes` on every `netops_init`
— no user action required. All produce `v_*_auto` views queryable via
`query_topology` with typed Pydantic output.

## Shipped recipes

| Concept | Vendor | Source command | View |
|---|---|---|---|
| `bgp_neighbors` | cisco_ios | `show bgp summary` | `v_bgp_neighbors_auto` |
| `bgp_neighbors` | cisco_ios | `show ip bgp summary` | (unioned) |
| `bgp_neighbors` | cisco_ios | `show bgp all summary` | (unioned) |
| `bgp_neighbors` | juniper_junos | `show bgp summary` | (unioned) |
| `bgp_neighbors` | arista_eos | `show ip bgp summary` | (unioned) |
| `ospf_neighbors` | cisco_ios | `show ip ospf neighbor` | `v_ospf_neighbors_auto` |
| `ospf_neighbors` | juniper_junos | `show ospf neighbor` | (unioned) |
| `ospf_neighbors` | arista_eos | `show ip ospf neighbor` | (unioned) |
| `topology_l2` | universal | `@topology_links` | `v_l2_links_auto` |

## Pydantic schemas

| View | Schema model |
|---|---|
| `v_bgp_neighbors_auto` | `olav_netops.schemas.topology.BGPSession` |
| `v_ospf_neighbors_auto` | `olav_netops.schemas.topology.OSPFAdjacency` |
| `v_l2_links_auto` | `olav_netops.schemas.topology.L2Link` |

## Adding new built-ins (repo contributor path)

Only olav-netops contributors edit shipped built-ins. The usual workflow:

1. Discover the recipe on real hardware (via `discover_recipe` agent tool)
2. Review the YAML output
3. Move the file from `~/.olav/config/recipes/user/` to
   `olav-netops/.olav/workspace/topology/recipes/builtin/` in a PR
4. Add the protocol's Pydantic model to `olav_netops.schemas.topology` if
   it's a new canonical concept
5. Update this list
