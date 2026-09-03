-- =============================================================================
-- Knowledge Layer Demo — Meridian Bank / Rosa's Bakery
-- Snowflake load script: core banking + loan/credit data
-- =============================================================================
-- Scope: only the tables under data/snowflake/ (core banking, loan/credit,
-- KYC, and reference lookups). Ownership data (data/ownership-seed/) is
-- deliberately NOT loaded here — per the demo narrative it belongs natively
-- in Neo4j, not Snowflake.
--
-- HOW TO RUN
-- 1. Edit the WAREHOUSE / DATABASE / SCHEMA names below if you want different ones.
-- 2. Get the 12 CSVs from data/snowflake/ onto the internal stage created below.
--    You cannot COPY INTO directly from your laptop — the files must be
--    staged first. Two options:
--      a) Snowsight UI: Data > Databases > [schema] > Stages > @csv_stage >
--         "+ Files" and upload all 12 CSVs from data/snowflake/.
--      b) SnowSQL CLI, from the data/snowflake/ directory:
--           snowsql -a <account> -u <user>
--           > USE DATABASE KNOWLEDGE_LAYER_DEMO;
--           > USE SCHEMA MERIDIAN_BANK;
--           > PUT file://*.csv @csv_stage AUTO_COMPRESS=TRUE OVERWRITE=TRUE;
-- 3. Run this whole script top to bottom in a Snowsight worksheet (or via
--    SnowSQL) once the files are staged.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 0. Context
-- ---------------------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS KNOWLEDGE_LAYER_DEMO;
CREATE SCHEMA IF NOT EXISTS KNOWLEDGE_LAYER_DEMO.MERIDIAN_BANK;
USE DATABASE KNOWLEDGE_LAYER_DEMO;
USE SCHEMA MERIDIAN_BANK;
-- USE WAREHOUSE <your_warehouse>;   -- uncomment and set if needed

-- ---------------------------------------------------------------------------
-- 1. File format + stage
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FILE FORMAT csv_ff
    TYPE = 'CSV'
    FIELD_DELIMITER = ','
    SKIP_HEADER = 1
    FIELD_OPTIONALLY_ENCLOSED_BY = '"'
    NULL_IF = ('', 'NULL')
    EMPTY_FIELD_AS_NULL = TRUE
    TRIM_SPACE = TRUE;

CREATE STAGE IF NOT EXISTS csv_stage
    FILE_FORMAT = csv_ff;

-- ---------------------------------------------------------------------------
-- 2. Reference / lookup tables
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE branches (
    branch_id     VARCHAR(10)  PRIMARY KEY,
    branch_name   VARCHAR(100),
    city          VARCHAR(50),
    state         VARCHAR(2),
    zip           VARCHAR(10),
    opened_date   DATE
);

CREATE OR REPLACE TABLE industry_codes (
    industry_code  VARCHAR(10) PRIMARY KEY,
    industry_name  VARCHAR(100)
);

CREATE OR REPLACE TABLE product_types (
    product_type_code  VARCHAR(10) PRIMARY KEY,
    product_type_name  VARCHAR(100),
    category           VARCHAR(20)
);

CREATE OR REPLACE TABLE employees (
    employee_id  VARCHAR(10) PRIMARY KEY,
    full_name    VARCHAR(100),
    role         VARCHAR(50),
    branch_id    VARCHAR(10) REFERENCES branches(branch_id),
    hire_date    DATE
);

-- ---------------------------------------------------------------------------
-- 3. Core banking
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE customers (
    customer_id               VARCHAR(10) PRIMARY KEY,
    customer_name             VARCHAR(200),
    customer_type             VARCHAR(20),
    industry_code             VARCHAR(10) REFERENCES industry_codes(industry_code),
    ein                       VARCHAR(15),
    founded_date              DATE,
    relationship_start_date   DATE,
    branch_id                 VARCHAR(10) REFERENCES branches(branch_id),
    relationship_manager_id   VARCHAR(10) REFERENCES employees(employee_id),
    address                   VARCHAR(200),
    city                      VARCHAR(50),
    state                     VARCHAR(2),
    zip                       VARCHAR(10),
    parent_customer_id        VARCHAR(10) REFERENCES customers(customer_id),
    customer_seq_id           NUMBER(18,0) UNIQUE  -- GDS long-ID surrogate; see section 7 below
);

CREATE OR REPLACE TABLE accounts (
    account_id                VARCHAR(10) PRIMARY KEY,
    customer_id               VARCHAR(10) REFERENCES customers(customer_id),
    product_type_code         VARCHAR(10) REFERENCES product_types(product_type_code),
    open_date                 DATE,
    current_balance           NUMBER(15,2),
    avg_monthly_balance_ttm   NUMBER(15,2),
    status                    VARCHAR(20),
    branch_id                 VARCHAR(10) REFERENCES branches(branch_id)
);

CREATE OR REPLACE TABLE account_transactions (
    transaction_id     VARCHAR(12) PRIMARY KEY,
    account_id         VARCHAR(10) REFERENCES accounts(account_id),
    transaction_date   DATE,
    transaction_type   VARCHAR(30),
    amount             NUMBER(15,2),
    running_balance    NUMBER(15,2)
);

CREATE OR REPLACE TABLE kyc_status (
    customer_id        VARCHAR(10) PRIMARY KEY REFERENCES customers(customer_id),
    kyc_status         VARCHAR(30),
    last_review_date   DATE,
    risk_rating        VARCHAR(10),
    notes              VARCHAR(500)
);

-- ---------------------------------------------------------------------------
-- 4. Loan / credit
-- ---------------------------------------------------------------------------
CREATE OR REPLACE TABLE loan_facilities (
    facility_id               VARCHAR(15) PRIMARY KEY,
    customer_id               VARCHAR(10) REFERENCES customers(customer_id),
    product_type_code         VARCHAR(10) REFERENCES product_types(product_type_code),
    original_amount           NUMBER(15,2),
    current_balance           NUMBER(15,2),
    origination_date          DATE,
    maturity_date              DATE,
    interest_rate             NUMBER(5,2),
    payment_status            VARCHAR(20),
    days_past_due             NUMBER(5,0),
    delinquency_flag          BOOLEAN,
    relationship_manager_id   VARCHAR(10) REFERENCES employees(employee_id)
);

CREATE OR REPLACE TABLE payment_history (
    payment_id         VARCHAR(12) PRIMARY KEY,
    facility_id        VARCHAR(15) REFERENCES loan_facilities(facility_id),
    due_date           DATE,
    scheduled_amount   NUMBER(15,2),
    paid_amount        NUMBER(15,2),
    paid_date          DATE,
    days_late          NUMBER(5,0),
    status             VARCHAR(20)
);

CREATE OR REPLACE TABLE credit_score_history (
    score_id       VARCHAR(12) PRIMARY KEY,
    customer_id    VARCHAR(10) REFERENCES customers(customer_id),
    score_date     DATE,
    credit_score   NUMBER(5,0),
    score_band     VARCHAR(20)
);

CREATE OR REPLACE TABLE loan_applications (
    application_id         VARCHAR(15) PRIMARY KEY,
    customer_id            VARCHAR(10) REFERENCES customers(customer_id),
    requested_amount       NUMBER(15,2),
    purpose                VARCHAR(200),
    application_date       DATE,
    status                 VARCHAR(30),
    loan_officer_id        VARCHAR(10) REFERENCES employees(employee_id),
    term_years             NUMBER(3,0),
    requested_rate_type    VARCHAR(20)
);

-- ---------------------------------------------------------------------------
-- 5. Load data (respects FK order: lookups -> customers -> everything else)
-- ---------------------------------------------------------------------------
COPY INTO branches               FROM @csv_stage/branches.csv               FILE_FORMAT = csv_ff ON_ERROR = 'ABORT_STATEMENT';
COPY INTO industry_codes         FROM @csv_stage/industry_codes.csv         FILE_FORMAT = csv_ff ON_ERROR = 'ABORT_STATEMENT';
COPY INTO product_types          FROM @csv_stage/product_types.csv          FILE_FORMAT = csv_ff ON_ERROR = 'ABORT_STATEMENT';
COPY INTO employees              FROM @csv_stage/employees.csv              FILE_FORMAT = csv_ff ON_ERROR = 'ABORT_STATEMENT';
COPY INTO customers              FROM @csv_stage/customers.csv              FILE_FORMAT = csv_ff ON_ERROR = 'ABORT_STATEMENT';
COPY INTO accounts               FROM @csv_stage/accounts.csv               FILE_FORMAT = csv_ff ON_ERROR = 'ABORT_STATEMENT';
COPY INTO account_transactions   FROM @csv_stage/account_transactions.csv   FILE_FORMAT = csv_ff ON_ERROR = 'ABORT_STATEMENT';
COPY INTO kyc_status              FROM @csv_stage/kyc_status.csv              FILE_FORMAT = csv_ff ON_ERROR = 'ABORT_STATEMENT';
COPY INTO loan_facilities        FROM @csv_stage/loan_facilities.csv        FILE_FORMAT = csv_ff ON_ERROR = 'ABORT_STATEMENT';
COPY INTO payment_history        FROM @csv_stage/payment_history.csv        FILE_FORMAT = csv_ff ON_ERROR = 'ABORT_STATEMENT';
COPY INTO credit_score_history   FROM @csv_stage/credit_score_history.csv   FILE_FORMAT = csv_ff ON_ERROR = 'ABORT_STATEMENT';
COPY INTO loan_applications      FROM @csv_stage/loan_applications.csv      FILE_FORMAT = csv_ff ON_ERROR = 'ABORT_STATEMENT';

-- ---------------------------------------------------------------------------
-- 6. Sanity checks — expected row counts
-- ---------------------------------------------------------------------------
SELECT 'branches' AS table_name, COUNT(*) AS row_count FROM branches
UNION ALL SELECT 'industry_codes', COUNT(*) FROM industry_codes
UNION ALL SELECT 'product_types', COUNT(*) FROM product_types
UNION ALL SELECT 'employees', COUNT(*) FROM employees
UNION ALL SELECT 'customers', COUNT(*) FROM customers
UNION ALL SELECT 'accounts', COUNT(*) FROM accounts
UNION ALL SELECT 'account_transactions', COUNT(*) FROM account_transactions
UNION ALL SELECT 'kyc_status', COUNT(*) FROM kyc_status
UNION ALL SELECT 'loan_facilities', COUNT(*) FROM loan_facilities
UNION ALL SELECT 'payment_history', COUNT(*) FROM payment_history
UNION ALL SELECT 'credit_score_history', COUNT(*) FROM credit_score_history
UNION ALL SELECT 'loan_applications', COUNT(*) FROM loan_applications
ORDER BY table_name;

-- Expected: branches=5, industry_codes=16, product_types=8, employees=10,
-- customers=83, accounts=104, account_transactions=5911, kyc_status=83,
-- loan_facilities=52, payment_history=1070, credit_score_history=960,
-- loan_applications=15

-- Spot-check the Beat 3 story fact: Rosa's Bakery (C001) looks clean on its
-- own; the connected delinquency only appears once you join through
-- ownership (loaded separately in Neo4j) to Alvarez Distribution Co (C002).
SELECT * FROM customers WHERE customer_id IN ('C001', 'C002');
SELECT * FROM loan_facilities WHERE customer_id IN ('C001', 'C002');
SELECT * FROM loan_applications WHERE customer_id = 'C001';

-- ---------------------------------------------------------------------------
-- 7. Corporate hierarchy fact (Virtual Graph GDS vs. SQL)
-- ---------------------------------------------------------------------------
-- Rosa's Bakery (C001) and Alvarez Distribution Co (C002) also connect a
-- second way, entirely within this Snowflake table via self-referencing
-- parent_customer_id -- no cross-system join required:
--   C001 -> C082 (Alvarez Family Holdings LLC) -> C081 (Cedarville Investment Group)
--   C002 -> C083 (Alvarez Logistics Holdings LLC) -> C081 (Cedarville Investment Group)
--
-- NOTE on the actual capability gap: Virtual Graph's Cypher coverage does NOT
-- include variable-length paths (-[:REL*1..n]->), so this fact alone is
-- something a recursive CTE (below) or a hand-written fixed-depth join can
-- also find in plain SQL -- see load_snowflake.sql history / README for the
-- corrected framing. The genuine, docs-confirmed capability gap is running
-- GDS graph algorithms (PageRank, Louvain community detection, WCC, etc.) via
-- a Cypher projection directly over this Virtual Graph -- see README.md,
-- "Corporate hierarchy: a reason to use Virtual Graph over plain SQL".
-- customer_seq_id below exists because GDS requires a single-column unsigned
-- integer surrogate ID on every node table it projects.
SELECT * FROM customers WHERE customer_id IN ('C081', 'C082', 'C083');
