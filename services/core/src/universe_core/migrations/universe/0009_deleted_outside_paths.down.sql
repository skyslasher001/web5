-- Reverts 0009_deleted_outside_paths: back to the original path, where that path is still free.

UPDATE items
SET path = json_extract(metadata, '$.trashed_from')
WHERE trashed_at IS NOT NULL
  AND json_extract(metadata, '$.deleted_outside_app') = 1
  AND path LIKE '.universe/trash/%'
  AND json_extract(metadata, '$.trashed_from') IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM items AS other WHERE other.path = json_extract(items.metadata, '$.trashed_from'));
