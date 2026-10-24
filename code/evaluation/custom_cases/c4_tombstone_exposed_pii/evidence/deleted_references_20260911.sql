-- Custom evaluation case: point-in-time database snapshot
-- Dialect: SQLite-compatible SQL
-- Captured at: 2026-09-11T12:00:00Z

BEGIN TRANSACTION;
CREATE TABLE identity_tombstones (resource_id TEXT PRIMARY KEY, origin_system TEXT NOT NULL, collection_name TEXT NOT NULL, record_json TEXT NOT NULL, updated_at TEXT NOT NULL);
INSERT INTO "identity_tombstones" VALUES('tombstone_9401','identity_service','deleted_customer_references','{"resource_id": "tombstone_9401", "subject_reference": "user_c4", "name": "Oskar Lindqvist", "email": "oskar.lindqvist@icloud.com", "phone": "+46 76 204 9913", "email_hash": "c1bb29bb00a9ddfa83548b623b2e8440b13896d3753eb7117ed11b63ac5621b8", "account_status": "DELETED"}','2026-09-11T12:00:00Z');
COMMIT;
