# draw.io XML Generation Rules — Quick Reference

Use for generating editable draw.io diagrams. Load only when needed.

## Minimal XML Structure

```xml
<mxGraphModel>
  <root>
    <mxCell id="0"/>
    <mxCell id="1" parent="0"/>
    <!-- Nodes and edges go here (parent="1") -->
  </root>
</mxGraphModel>
```

## Router Node

```xml
<mxCell id="R1" value="R1&#xa;AS 65001" style="shape=mxgraph.cisco.routers.router;html=1;pointerEvents=1;dashed=0;fillColor=#036897;strokeColor=#ffffff;strokeWidth=2;verticalLabelPosition=bottom;verticalAlign=top;align=center;outlineConnect=0;"
  vertex="1" parent="1">
  <mxGeometry x="80" y="160" width="68" height="48" as="geometry"/>
</mxCell>
```

## Switch Node

```xml
<mxCell id="SW1" value="SW1" style="shape=mxgraph.cisco.switches.workgroup_switch;html=1;pointerEvents=1;dashed=0;fillColor=#036897;strokeColor=#ffffff;strokeWidth=2;verticalLabelPosition=bottom;verticalAlign=top;align=center;outlineConnect=0;"
  vertex="1" parent="1">
  <mxGeometry x="240" y="160" width="68" height="44" as="geometry"/>
</mxCell>
```

## Edge (Link)

```xml
<mxCell id="e1" value="10.0.0.0/30" style="endArrow=none;html=1;" edge="1" source="R1" target="R2" parent="1">
  <mxGeometry relative="1" as="geometry"/>
</mxCell>
```

## Common Style Parameters

| Parameter | Values | Effect |
|-----------|--------|--------|
| `fillColor` | hex | Node fill colour (`#036897` = Cisco blue) |
| `strokeColor` | hex | Border colour |
| `fontStyle` | 0,1,2,4 | Normal, Bold, Italic, Underline |
| `verticalLabelPosition` | bottom/top | Label placement |
| `dashed` | 0/1 | Dashed border |
| `shape` | mxgraph.cisco.* | Cisco stencil shape |

## Common Cisco Shapes

```
mxgraph.cisco.routers.router
mxgraph.cisco.switches.workgroup_switch
mxgraph.cisco.firewalls.firewall
mxgraph.cisco.servers.standard_server
mxgraph.cisco.clouds.cloud
mxgraph.cisco.computers_and_peripherals.pc
```

## Layout Tips

- Use a 80px grid: position nodes at multiples of 80
- Typical router: width=68, height=48; switch: width=68, height=44
- Group related devices in rectangular containers (swimlanes)

## Export via OLAV

```python
format_and_export(content=xml_string, format="drawio", filename="topology")
# → exports/topology.drawio
```
