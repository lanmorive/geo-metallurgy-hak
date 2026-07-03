// НЕ МЕНЯТЬ БЕЗ СОГЛАСОВАНИЯ ВСЕЙ КОМАНДЫ
// Constraints и индексы Neo4j для графа знаний «Научный клубок»

// --- Unique constraints (label, name_norm) ---
CREATE CONSTRAINT material_name IF NOT EXISTS
FOR (n:Material) REQUIRE (n.name_norm) IS UNIQUE;

CREATE CONSTRAINT process_name IF NOT EXISTS
FOR (n:Process) REQUIRE (n.name_norm) IS UNIQUE;

CREATE CONSTRAINT equipment_name IF NOT EXISTS
FOR (n:Equipment) REQUIRE (n.name_norm) IS UNIQUE;

CREATE CONSTRAINT property_name IF NOT EXISTS
FOR (n:Property) REQUIRE (n.name_norm) IS UNIQUE;

CREATE CONSTRAINT experiment_name IF NOT EXISTS
FOR (n:Experiment) REQUIRE (n.name_norm) IS UNIQUE;

CREATE CONSTRAINT publication_name IF NOT EXISTS
FOR (n:Publication) REQUIRE (n.name_norm) IS UNIQUE;

CREATE CONSTRAINT expert_name IF NOT EXISTS
FOR (n:Expert) REQUIRE (n.name_norm) IS UNIQUE;

CREATE CONSTRAINT organization_name IF NOT EXISTS
FOR (n:Organization) REQUIRE (n.name_norm) IS UNIQUE;

CREATE CONSTRAINT facility_name IF NOT EXISTS
FOR (n:Facility) REQUIRE (n.name_norm) IS UNIQUE;

// --- Fulltext index ---
CREATE FULLTEXT INDEX entity_fulltext IF NOT EXISTS
FOR (n:Material|Process|Equipment|Property|Experiment|Publication|Expert|Organization|Facility)
ON EACH [n.name, n.name_norm, n.aliases];

// --- Vector index (bge-m3, 1024 dimensions) ---
CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS
FOR (n:Chunk) ON (n.embedding)
OPTIONS {indexConfig: {
  `vector.dimensions`: 1024,
  `vector.similarity_function`: 'cosine'
}};
