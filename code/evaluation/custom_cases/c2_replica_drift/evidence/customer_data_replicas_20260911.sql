-- Custom evaluation case: point-in-time database snapshot
-- Dialect: SQLite-compatible SQL
-- Captured at: 2026-09-11T12:00:00Z

BEGIN TRANSACTION;
CREATE TABLE customer_data_primary (resource_id TEXT PRIMARY KEY, origin_system TEXT NOT NULL, collection_name TEXT NOT NULL, record_json TEXT NOT NULL, updated_at TEXT NOT NULL);
INSERT INTO "customer_data_primary" VALUES('account_9202','account_service','customer_profiles','{"resource_id": "account_9202", "name": "Ines Carvalho", "email": "ines.carvalho@gmail.com", "phone": "+351 912 330 448", "account_status": "ACTIVE"}','2026-09-11T12:00:00Z');
CREATE TABLE customer_data_reporting_replica (resource_id TEXT PRIMARY KEY, origin_system TEXT NOT NULL, collection_name TEXT NOT NULL, record_json TEXT NOT NULL, updated_at TEXT NOT NULL);
INSERT INTO "customer_data_reporting_replica" VALUES('account_9201','account_service','customer_profiles','{"resource_id": "account_9201", "name": "Tomás Bergqvist", "email": "tomas.bergqvist@outlook.com", "phone": "+46 73 551 2047", "account_status": "ACTIVE"}','2026-09-11T12:00:00Z');
INSERT INTO "customer_data_reporting_replica" VALUES('account_9202','account_service','customer_profiles','{"resource_id": "account_9202", "name": "Ines Carvalho", "email": "ines.carvalho@gmail.com", "phone": "+351 912 330 448", "account_status": "ACTIVE"}','2026-09-11T12:00:00Z');
COMMIT;
