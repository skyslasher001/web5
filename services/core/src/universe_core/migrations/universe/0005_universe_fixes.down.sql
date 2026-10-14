-- Reverts 0005_universe_fixes.

DELETE FROM settings WHERE key = 'vault.wikilinks_backfill';
DROP TABLE removed_items;
