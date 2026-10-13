// An item's picture: its thumbnail when it has one, otherwise its type glyph in the type's hue.
import type { ItemSummary } from '@universe/shared-types';
import { tokens } from '@universe/design-tokens';
import { ITEM_TYPES } from '../lib/itemTypes';
import { useThumbnail } from '../lib/queries';

export function TypeGlyph({ item, size = 18 }: { item: Pick<ItemSummary, 'type'>; size?: number }) {
  const style = ITEM_TYPES[item.type];
  return (
    <style.Icon
      aria-label={style.label}
      role="img"
      style={{ width: size, height: size, color: tokens.color[style.hue] }}
    />
  );
}

export function ItemVisual({ item, className = '' }: { item: ItemSummary; className?: string }) {
  const url = useThumbnail(item.id, item.has_thumbnail);
  if (url) {
    return <img src={url} alt="" draggable={false} className={`object-cover ${className}`} />;
  }
  const hue = tokens.color[ITEM_TYPES[item.type].hue];
  return (
    <div
      className={`flex items-center justify-center ${className}`}
      style={{ background: `radial-gradient(circle at 50% 40%, ${hue}22, transparent 70%)` }}
    >
      <TypeGlyph item={item} size={32} />
    </div>
  );
}

const STATUS_COLOR: Record<ItemSummary['pipeline_status'], string> = {
  pending: tokens.color.slate,
  processing: tokens.color.amber,
  done: tokens.color.green,
  failed: tokens.color.danger,
};

const STATUS_LABEL: Record<ItemSummary['pipeline_status'], string> = {
  pending: 'Waiting to be processed',
  processing: 'Being processed',
  done: 'Processed: searchable by keyword and meaning',
  failed: 'Processing failed (see the item for details)',
};

export function PipelineDot({ status }: { status: ItemSummary['pipeline_status'] }) {
  return (
    <span
      role="img"
      aria-label={STATUS_LABEL[status]}
      title={STATUS_LABEL[status]}
      className={`inline-block size-1.5 shrink-0 rounded-full ${status === 'processing' ? 'orb-breathe' : ''}`}
      style={{ background: STATUS_COLOR[status] }}
    />
  );
}
