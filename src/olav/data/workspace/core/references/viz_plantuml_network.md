# PlantUML Network Topology — Quick Reference

Use for professional network diagrams with Cisco/Juniper stencils. Load only when needed.

## Basic Network Diagram

```plantuml
@startuml
!include <cisco/routers/router>
!include <cisco/switches/workgroup_switch>
!include <cisco/firewalls/firewall>

skinparam monochrome false
skinparam backgroundColor white

ROUTER(R1, "R1\nAS 65001", router)
ROUTER(R2, "R2\nAS 65002", router)
WORKGROUP_SWITCH(SW1, "SW1", switch)

R1 -- R2 : 10.0.0.0/30\neBGP
R1 -- SW1 : 192.168.1.0/24
@enduml
```

## Available Cisco Stencils

```
<cisco/routers/router>           ROUTER(id, label, router)
<cisco/switches/workgroup_switch> WORKGROUP_SWITCH(id, label, switch)
<cisco/firewalls/firewall>       FIREWALL(id, label, firewall)
<cisco/servers/standard_server>  STANDARD_SERVER(id, label, server)
<cisco/clouds/cloud>             CLOUD(id, label, cloud)
<cisco/generic_buildings/building> BUILDING(id, label, building)
```

## Link Styles

```plantuml
A -- B           ' undirected link
A --> B          ' directed link
A --> B : label  ' with label
A -[#red]-> B    ' coloured
A =[#blue]=> B   ' thick
A -[dashed]-> B  ' dashed
```

## Grouping with Frames

```plantuml
frame "Data Center" {
    ROUTER(R1, R1, router)
    WORKGROUP_SWITCH(SW1, SW1, switch)
}
frame "WAN" {
    CLOUD(Internet, Internet, cloud)
}
```

## Skinparam Customizations

```plantuml
skinparam defaultFontSize 12
skinparam padding 5
skinparam ArrowColor DarkGray
skinparam LinetypeOrtho        ' right-angle connectors
```

## Rendering Notes

- Wrap in ` ```plantuml ` fenced code blocks
- OLAV can generate PlantUML source; actual rendering requires a PlantUML server or plugin
- For topology export use `format_and_export(format="plantuml")`
