-- Custom evaluation case: point-in-time database snapshot
-- Dialect: SQLite-compatible SQL
-- Captured at: 2026-09-11T12:00:00Z

BEGIN TRANSACTION;
CREATE TABLE customer_data_primary (resource_id TEXT PRIMARY KEY, origin_system TEXT NOT NULL, collection_name TEXT NOT NULL, record_json TEXT NOT NULL, updated_at TEXT NOT NULL);
INSERT INTO "customer_data_primary" VALUES('account_9101','account_service','customer_profiles','{"resource_id": "account_9101", "name": "Linnea Holm", "email": "linnea.holm@proton.me", "phone": "+46 70 412 8836", "account_status": "ACTIVE"}','2026-09-11T12:00:00Z');
COMMIT;
