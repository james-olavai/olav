# OSPF Best Practices

## Neighbor Stuck in INIT State

The neighbor is stuck in INIT state when:
- Hello packets are received but negotiation fails
- Check the neighbor hello/dead timers
- Verify area numbers match

Solutions:
- Adjust timers: `ip ospf hello-interval 10`
- Check OSPF network types match
- Verify interface MTU settings
