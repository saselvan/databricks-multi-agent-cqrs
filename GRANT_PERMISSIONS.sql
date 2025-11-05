-- Unity Catalog Permissions for Multi-Agent Demo
-- Run these SQL commands in a Databricks SQL Editor AFTER running 01_setup_cqrs_tables.py
-- 
-- These grants give the Service Principals access to:
-- - Catalog and schema (USE permissions)
-- - UC Volumes (READ/WRITE for file access)
-- - Delta Tables (SELECT/MODIFY for data and CQRS events)

-- Replace with your values:
-- <CATALOG_NAME>: Your catalog name (e.g., test_demo)
-- <SCHEMA_NAME>: Your schema name (e.g., multi_agent)
-- <EXTRACTION_SP_CLIENT_ID>: Your extraction SP's Application ID
-- <SUMMARIZATION_SP_CLIENT_ID>: Your summarization SP's Application ID

-- ============================================================================
-- EXTRACTION SP PERMISSIONS
-- ============================================================================

-- Catalog access (prerequisite for all other permissions)
GRANT USE CATALOG ON CATALOG <CATALOG_NAME> TO `<EXTRACTION_SP_CLIENT_ID>`;

-- Schema access (prerequisite for volume/table access)
GRANT USE SCHEMA ON SCHEMA <CATALOG_NAME>.<SCHEMA_NAME> TO `<EXTRACTION_SP_CLIENT_ID>`;

-- Volume access (read source PDFs)
GRANT READ VOLUME ON VOLUME <CATALOG_NAME>.<SCHEMA_NAME>.source_pdfs TO `<EXTRACTION_SP_CLIENT_ID>`;

-- Table access (write extracted documents and CQRS events)
-- CRITICAL: Use MODIFY (not INSERT) for SQL Statement Execution API
GRANT SELECT, MODIFY ON TABLE <CATALOG_NAME>.staging.extracted_documents TO `<EXTRACTION_SP_CLIENT_ID>`;
GRANT SELECT, MODIFY ON TABLE <CATALOG_NAME>.<SCHEMA_NAME>.job_events TO `<EXTRACTION_SP_CLIENT_ID>`;


-- ============================================================================
-- SUMMARIZATION SP PERMISSIONS
-- ============================================================================

-- Catalog access
GRANT USE CATALOG ON CATALOG <CATALOG_NAME> TO `<SUMMARIZATION_SP_CLIENT_ID>`;

-- Schema access
GRANT USE SCHEMA ON SCHEMA <CATALOG_NAME>.<SCHEMA_NAME> TO `<SUMMARIZATION_SP_CLIENT_ID>`;

-- Volume access (write summaries)
GRANT WRITE VOLUME ON VOLUME <CATALOG_NAME>.<SCHEMA_NAME>.summaries TO `<SUMMARIZATION_SP_CLIENT_ID>`;

-- Table access (write summaries and CQRS events)
-- CRITICAL: Use MODIFY (not INSERT) for SQL Statement Execution API
GRANT SELECT, MODIFY ON TABLE <CATALOG_NAME>.staging.summaries TO `<SUMMARIZATION_SP_CLIENT_ID>`;
GRANT SELECT, MODIFY ON TABLE <CATALOG_NAME>.<SCHEMA_NAME>.job_events TO `<SUMMARIZATION_SP_CLIENT_ID>`;


-- ============================================================================
-- VERIFICATION
-- ============================================================================

-- Verify grants for extraction SP:
SHOW GRANTS ON CATALOG <CATALOG_NAME> FOR `<EXTRACTION_SP_CLIENT_ID>`;
SHOW GRANTS ON VOLUME <CATALOG_NAME>.<SCHEMA_NAME>.source_pdfs FOR `<EXTRACTION_SP_CLIENT_ID>`;

-- Verify grants for summarization SP:
SHOW GRANTS ON CATALOG <CATALOG_NAME> FOR `<SUMMARIZATION_SP_CLIENT_ID>`;
SHOW GRANTS ON VOLUME <CATALOG_NAME>.<SCHEMA_NAME>.summaries FOR `<SUMMARIZATION_SP_CLIENT_ID>`;
