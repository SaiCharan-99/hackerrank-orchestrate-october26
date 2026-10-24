-- Custom evaluation case: point-in-time database snapshot
-- Dialect: SQLite-compatible SQL
-- Captured at: 2026-09-11T12:00:00Z

BEGIN TRANSACTION;
CREATE TABLE customer_data_primary (resource_id TEXT PRIMARY KEY, origin_system TEXT NOT NULL, collection_name TEXT NOT NULL, record_json TEXT NOT NULL, updated_at TEXT NOT NULL);
INSERT INTO "customer_data_primary" VALUES('account_9621','account_service','customer_profiles','{"resource_id": "account_9621", "name": "Mei Tanaka", "email": "mei.tanaka@outlook.jp", "phone": "+81 90 4417 2280", "account_status": "ACTIVE"}','2026-09-11T12:00:00Z');
COMMIT;
