// Neo4j Seed Script - Test Cabal Clusters
// Run with: docker exec solana-intel-engine-neo4j-1 cypher-shell -u neo4j -p password < db/seeds/cabals.cypher

// ===========================================================================
// CABAL CLUSTER 1: "Pump & Dump Squad" - 5 wallets that trade together
// ===========================================================================
MERGE (c1:Cluster {cluster_id: "cabal_pump_dump_001"})
SET c1.member_count = 5,
    c1.shared_contracts_count = 12,
    c1.updated_at = datetime(),
    c1.name = "Pump & Dump Squad";

// Wallet members
MERGE (w1:Wallet {address: "PumpDump1111111111111111111111111111111111"})
MERGE (w2:Wallet {address: "PumpDump2222222222222222222222222222222222"})
MERGE (w3:Wallet {address: "PumpDump3333333333333333333333333333333333"})
MERGE (w4:Wallet {address: "PumpDump4444444444444444444444444444444444"})
MERGE (w5:Wallet {address: "PumpDump5555555555555555555555555555555555"})

// Add to cluster
MERGE (w1)-[:MEMBER_OF]->(c1)
MERGE (w2)-[:MEMBER_OF]->(c1)
MERGE (w3)-[:MEMBER_OF]->(c1)
MERGE (w4)-[:MEMBER_OF]->(c1)
MERGE (w5)-[:MEMBER_OF]->(c1);

// ===========================================================================
// CABAL CLUSTER 2: "MEV Mafia" - 3 wallets coordinating MEV extraction
// ===========================================================================
MERGE (c2:Cluster {cluster_id: "cabal_mev_mafia_002"})
SET c2.member_count = 3,
    c2.shared_contracts_count = 8,
    c2.updated_at = datetime(),
    c2.name = "MEV Mafia";

MERGE (m1:Wallet {address: "MevMafia111111111111111111111111111111111"})
MERGE (m2:Wallet {address: "MevMafia222222222222222222222222222222222"})
MERGE (m3:Wallet {address: "MevMafia333333333333333333333333333333333"})

MERGE (m1)-[:MEMBER_OF]->(c2)
MERGE (m2)-[:MEMBER_OF]->(c2)
MERGE (m3)-[:MEMBER_OF]->(c2);

// ===========================================================================
// CORRELATION EDGES - Wallets that traded together
// ===========================================================================
MERGE (w1)-[:CORRELATED_WITH {score: 0.95, occurrences: 15, last_seen: datetime()}]->(w2)
MERGE (w2)-[:CORRELATED_WITH {score: 0.88, occurrences: 12, last_seen: datetime()}]->(w3)
MERGE (w3)-[:CORRELATED_WITH {score: 0.92, occurrences: 14, last_seen: datetime()}]->(w4)
MERGE (w4)-[:CORRELATED_WITH {score: 0.85, occurrences: 10, last_seen: datetime()}]->(w5)
MERGE (w1)-[:CORRELATED_WITH {score: 0.78, occurrences: 8, last_seen: datetime()}]->(w5)

MERGE (m1)-[:CORRELATED_WITH {score: 0.97, occurrences: 20, last_seen: datetime()}]->(m2)
MERGE (m2)-[:CORRELATED_WITH {score: 0.91, occurrences: 16, last_seen: datetime()}]->(m3)
MERGE (m1)-[:CORRELATED_WITH {score: 0.89, occurrences: 14, last_seen: datetime()}]->(m3);

// ===========================================================================
// RETURN summary
// ===========================================================================
MATCH (c:Cluster) RETURN c.cluster_id, c.member_count, c.name;
