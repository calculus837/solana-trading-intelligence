"""Seed Neo4j with test cabal clusters."""
from neo4j import GraphDatabase

driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))

with driver.session() as session:
    # Cluster 1: Pump & Dump Squad (5 members)
    session.run("""
        MERGE (c1:Cluster {cluster_id: "cabal_pump_dump_001"})
        SET c1.member_count = 5, c1.shared_contracts_count = 12, c1.name = "Pump And Dump Squad"
    """)
    
    for i in range(1, 6):
        addr = f"PumpDump{i}111111111111111111111111111111111"
        session.run("""
            MERGE (w:Wallet {address: $addr})
            MERGE (c:Cluster {cluster_id: "cabal_pump_dump_001"})
            MERGE (w)-[:MEMBER_OF]->(c)
        """, addr=addr)
    
    # Cluster 2: MEV Mafia (3 members)
    session.run("""
        MERGE (c2:Cluster {cluster_id: "cabal_mev_mafia_002"})
        SET c2.member_count = 3, c2.shared_contracts_count = 8, c2.name = "MEV Mafia"
    """)
    
    for i in range(1, 4):
        addr = f"MevMafia{i}11111111111111111111111111111111"
        session.run("""
            MERGE (w:Wallet {address: $addr})
            MERGE (c:Cluster {cluster_id: "cabal_mev_mafia_002"})
            MERGE (w)-[:MEMBER_OF]->(c)
        """, addr=addr)
    
    # Verify
    result = session.run("MATCH (c:Cluster) RETURN c.cluster_id, c.member_count, c.name")
    print("=== Clusters Created ===")
    for record in result:
        print(f"  {record['c.name']} ({record['c.member_count']} members) - {record['c.cluster_id']}")
    
    result = session.run("MATCH (w:Wallet)-[:MEMBER_OF]->(c:Cluster) RETURN count(w) as wallet_count")
    print(f"\nTotal wallets linked to clusters: {result.single()['wallet_count']}")

driver.close()
print("\n✅ Test cabal data seeded successfully!")
