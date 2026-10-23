-- Items trashed because their file was deleted outside the app used to keep their original path (UNIQUE), so a
-- new file at that path could never be imported, and purging the old item could delete the new file. Move them
-- to their trash folder, as `purge.trash` and now `ingest.deleted_outside` store a trashed item; the old path is
-- kept as `trashed_from`. The file itself is already gone, so nothing on disk moves.

UPDATE items
SET path = '.universe/trash/' || id || '/' || replace(path, rtrim(path, replace(path, '/', '')), ''),
    metadata = json_set(metadata, '$.trashed_from', path)
WHERE trashed_at IS NOT NULL
  AND json_extract(metadata, '$.deleted_outside_app') = 1
  AND path NOT LIKE '.universe/trash/%';
