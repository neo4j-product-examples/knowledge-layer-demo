-- =============================================================================
-- Knowledge Layer Demo — incremental patch for the corporate hierarchy fact
-- Run this against the ALREADY-LOADED KNOWLEDGE_LAYER_DEMO.MERIDIAN_BANK
-- database. It does not touch any existing rows in accounts, transactions,
-- facilities, payments, scores, or applications -- only customers,
-- industry_codes, and kyc_status.
-- =============================================================================

USE DATABASE KNOWLEDGE_LAYER_DEMO;
USE SCHEMA MERIDIAN_BANK;

-- 1. Add the self-referencing column, plus a numeric surrogate key.
--    customer_seq_id is required for Virtual Graph's GDS support: GDS long
--    IDs must be a single, non-composite, unique unsigned-integer column, and
--    customer_id ("C001") doesn't qualify. See
--    https://neo4j.com/docs/virtual-graph/aura/gds/
ALTER TABLE customers ADD COLUMN parent_customer_id VARCHAR(10);
ALTER TABLE customers ADD COLUMN customer_seq_id NUMBER(18,0);

-- Snowflake doesn't allow a window function directly in UPDATE ... SET, so
-- populate customer_seq_id via a staging table (existing 80 customers get
-- IDs 1-80 in customer_id order; the 3 new holding-company rows inserted in
-- step 3 get 81-83 explicitly).
CREATE OR REPLACE TEMP TABLE _seq AS
    SELECT customer_id, ROW_NUMBER() OVER (ORDER BY customer_id) AS seq_id FROM customers;
UPDATE customers c SET customer_seq_id = s.seq_id FROM _seq s WHERE c.customer_id = s.customer_id;

-- 2. New industry code for the holding companies
INSERT INTO industry_codes (industry_code, industry_name) VALUES
    ('IND16', 'Holding Company / Investment Vehicle');

-- 3. Three new holding-company customer rows
--    C001 (Rosa's Bakery) -> C082 -> C081 <- C083 <- C002 (Alvarez Distribution Co)
--    (customer_seq_id assigned explicitly here since step 1's ROW_NUMBER ran
--    before these rows existed)
INSERT INTO customers
    (customer_id, customer_name, customer_type, industry_code, ein, founded_date,
     relationship_start_date, branch_id, relationship_manager_id, address, city, state, zip,
     parent_customer_id, customer_seq_id)
VALUES
    ('C081', 'Cedarville Investment Group', 'Business', 'IND16', '84-2001001',
     '2005-01-15', '2005-01-15', 'BR01', 'EMP001',
     '1 Investment Plaza', 'Cedarville', 'OH', '45314', NULL, 81),
    ('C082', 'Alvarez Family Holdings LLC', 'Business', 'IND16', '84-2001002',
     '2010-06-01', '2010-06-01', 'BR01', 'EMP001',
     '1 Investment Plaza Suite 200', 'Cedarville', 'OH', '45314', 'C081', 82),
    ('C083', 'Alvarez Logistics Holdings LLC', 'Business', 'IND16', '84-2001003',
     '2012-09-20', '2012-09-20', 'BR01', 'EMP001',
     '1 Investment Plaza Suite 210', 'Cedarville', 'OH', '45314', 'C081', 83);

ALTER TABLE customers ADD CONSTRAINT customer_seq_id_uk UNIQUE (customer_seq_id);

-- 4. Point the two story customers at their holding companies
UPDATE customers SET parent_customer_id = 'C082' WHERE customer_id = 'C001';
UPDATE customers SET parent_customer_id = 'C083' WHERE customer_id = 'C002';

-- 5. KYC records for the 3 new customers (kyc_status.customer_id is PK+FK,
--    so every row in customers needs one)
INSERT INTO kyc_status (customer_id, kyc_status, last_review_date, risk_rating, notes) VALUES
    ('C081', 'Verified', '2026-01-05', 'Low', 'Corporate structure entity; no direct deposit relationship'),
    ('C082', 'Verified', '2026-01-05', 'Low', 'Corporate structure entity; no direct deposit relationship'),
    ('C083', 'Verified', '2026-01-05', 'Low', 'Corporate structure entity; no direct deposit relationship');

-- 6. Verify
SELECT 'customers' AS table_name, COUNT(*) AS row_count FROM customers
UNION ALL SELECT 'industry_codes', COUNT(*) FROM industry_codes
UNION ALL SELECT 'kyc_status', COUNT(*) FROM kyc_status;
-- Expected: customers=83, industry_codes=16, kyc_status=83

SELECT customer_id, customer_name, parent_customer_id
FROM customers
WHERE customer_id IN ('C001', 'C002', 'C081', 'C082', 'C083')
ORDER BY customer_id;

-- 7. Note on this hierarchy fact by itself: a 1-hop or 2-hop self-join misses
--    that C001 and C002 share an ultimate parent (C081) -- they only meet at
--    hop 3 -- and this returns 0 rows on purpose:
SELECT a.customer_id, b.customer_id
FROM customers a
JOIN customers b ON a.parent_customer_id = b.parent_customer_id
WHERE a.customer_id = 'C001' AND b.customer_id = 'C002';

-- A recursive CTE finds it fine, once you know to write one:
WITH RECURSIVE ancestors AS (
    SELECT customer_id, parent_customer_id, customer_id AS root, 0 AS depth
    FROM customers
    WHERE customer_id IN ('C001', 'C002')
    UNION ALL
    SELECT c.customer_id, c.parent_customer_id, a.root, a.depth + 1
    FROM customers c
    JOIN ancestors a ON c.customer_id = a.parent_customer_id
    WHERE a.depth < 5
)
SELECT root, customer_id AS ancestor, depth FROM ancestors ORDER BY root, depth;

-- IMPORTANT: Virtual Graph's Cypher coverage does not support variable-length
-- path patterns (-[:REL*1..n]->), so a single-relationship-type hierarchy
-- like this one is NOT, by itself, a capability SQL can't also do -- a fixed
-- 3-hop pattern in Cypher and a 3-hop join/recursive CTE in SQL both work.
-- See https://neo4j.com/docs/virtual-graph/aura/cypher-coverage/

-- 8. The genuine, docs-confirmed capability gap: Virtual Graph supports
-- running GDS graph algorithms (PageRank, Louvain community detection,
-- Weakly Connected Components, etc.) via a Cypher projection directly over
-- this table -- no SQL equivalent, since these are iterative/heuristic graph
-- computations, not joins. See https://neo4j.com/docs/virtual-graph/aura/gds/
-- and README.md ("Corporate hierarchy: a reason to use Virtual Graph over
-- plain SQL") for the full explanation and example query. This is why
-- customer_seq_id (added in step 1) exists: GDS requires a single unsigned-
-- integer surrogate ID column on every node table it projects.
