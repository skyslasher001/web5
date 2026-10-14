-- Reverts 0002_vault. Vault files on disk are untouched; only the index is dropped.

DROP TABLE backups;
DROP TABLE api_keys;
DROP TABLE jobs;
DROP TABLE source_files;
DROP TABLE watched_folders;
DROP TABLE item_projects;
DROP TABLE item_tags;
DROP TABLE tags;
DROP TABLE items_trigram;
DROP TABLE items_fts;
DROP TRIGGER chunks_au;
DROP TRIGGER chunks_ad;
DROP TRIGGER chunks_ai;
DROP TABLE chunks_fts;
DROP TABLE chunks;
DROP TABLE item_stages;
DROP TABLE versions;
DROP TABLE items;
DROP TABLE sources;
