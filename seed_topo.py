
from datetime import date

from olav.core.database import get_database

# Note: reset_database() might be too aggressive if it drops tables that sync_schemas needs
# But for a manual test it's fine as long as we don't need the schema
# Actually, let's just clear the data if tables exist.
db = get_database()
sync_date = date.today().strftime("%Y-%m-%d")

tables = ["devices", "topology_links", "interfaces", "bgp_neighbors", "bgp_routes", "routes"]
for t in tables:
    try:
        db.conn.execute(f"DELETE FROM {t}")
    except:
        pass

# Devices
db.conn.execute("INSERT INTO devices (device_id, name, hostname, mgmt_ip, platform) VALUES (?, ?, ?, ?, ?)", ["R1", "R1", "R1", "10.0.0.1", "ios"])
db.conn.execute("INSERT INTO devices (device_id, name, hostname, mgmt_ip, platform) VALUES (?, ?, ?, ?, ?)", ["R2", "R2", "R2", "10.0.0.2", "ios"])
db.conn.execute("INSERT INTO devices (device_id, name, hostname, mgmt_ip, platform) VALUES (?, ?, ?, ?, ?)", ["R3", "R3", "R3", "10.0.0.3", "ios"])

# Links
db.conn.execute("""
    INSERT INTO topology_links 
    (link_id, source_device, source_interface, destination_device, destination_interface, discovery_protocol, link_type, link_status, first_seen, last_seen, sync_date)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)
""", ["link1", "R1", "Gi0/1", "R2", "Gi0/1", "CDP", "L2", "up", sync_date])

db.conn.execute("""
    INSERT INTO topology_links 
    (link_id, source_device, source_interface, destination_device, destination_interface, discovery_protocol, link_type, link_status, first_seen, last_seen, sync_date)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)
""", ["link2", "R2", "Gi0/2", "R3", "Gi0/1", "CDP", "L2", "up", sync_date])

print("Database seeded with R1--R2--R3 topology.")
