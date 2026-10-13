// How each item type looks: one semantic hue (ARCHITECTURE.md §6.2) always paired with an icon.
import type { ItemType } from '@universe/shared-types';
import {
  AudioLines,
  Code2,
  File,
  FileSpreadsheet,
  FileText,
  Folder,
  Image,
  Lightbulb,
  Link,
  type LucideIcon,
  Mic,
  Monitor,
  Music,
  NotebookPen,
  ScrollText,
  Video,
} from 'lucide-react';
import type { Hue } from './colors';

interface TypeStyle {
  label: string;
  plural: string;
  hue: Hue;
  Icon: LucideIcon;
}

export const ITEM_TYPES: Record<ItemType, TypeStyle> = {
  note: { label: 'Note', plural: 'Notes', hue: 'cyan', Icon: NotebookPen },
  idea: { label: 'Idea', plural: 'Ideas', hue: 'violet', Icon: Lightbulb },
  song: { label: 'Song', plural: 'Songs', hue: 'rose', Icon: Music },
  audio: { label: 'Audio', plural: 'Audio', hue: 'rose', Icon: AudioLines },
  voice_memo: { label: 'Voice memo', plural: 'Voice memos', hue: 'rose', Icon: Mic },
  photo: { label: 'Photo', plural: 'Photos', hue: 'amber', Icon: Image },
  screenshot: { label: 'Screenshot', plural: 'Screenshots', hue: 'amber', Icon: Monitor },
  video: { label: 'Video', plural: 'Videos', hue: 'amber', Icon: Video },
  document: { label: 'Document', plural: 'Documents', hue: 'blue', Icon: FileText },
  pdf: { label: 'PDF', plural: 'PDFs', hue: 'blue', Icon: ScrollText },
  spreadsheet: { label: 'Spreadsheet', plural: 'Spreadsheets', hue: 'blue', Icon: FileSpreadsheet },
  code_file: { label: 'Code', plural: 'Code', hue: 'green', Icon: Code2 },
  code_repo: { label: 'Repository', plural: 'Repositories', hue: 'green', Icon: Code2 },
  link: { label: 'Link', plural: 'Links', hue: 'slate', Icon: Link },
  transcript: { label: 'Transcript', plural: 'Transcripts', hue: 'cyan', Icon: FileText },
  folder: { label: 'Folder', plural: 'Folders', hue: 'slate', Icon: Folder },
  file: { label: 'File', plural: 'Files', hue: 'slate', Icon: File },
};

/** The type filter chips in the 2D views: grouped the way people ask for things. */
export const TYPE_CHIPS: { label: string; types: ItemType[] }[] = [
  { label: 'Notes', types: ['note', 'idea'] },
  { label: 'Docs', types: ['document', 'pdf', 'spreadsheet'] },
  { label: 'Photos', types: ['photo', 'screenshot'] },
  { label: 'Audio', types: ['song', 'audio', 'voice_memo'] },
  { label: 'Video', types: ['video'] },
  { label: 'Code', types: ['code_file', 'code_repo'] },
  { label: 'Links', types: ['link'] },
];

export function sameTypes(a: readonly ItemType[], b: readonly ItemType[]): boolean {
  return a.length === b.length && a.every((t) => b.includes(t));
}

/** Text with «marked» matches from search snippets, split for highlighting. */
export function splitMarks(snippet: string): { text: string; mark: boolean }[] {
  const parts: { text: string; mark: boolean }[] = [];
  const pattern = /«([^»]*)»/g;
  let last = 0;
  for (let match = pattern.exec(snippet); match; match = pattern.exec(snippet)) {
    if (match.index > last) parts.push({ text: snippet.slice(last, match.index), mark: false });
    parts.push({ text: match[1] ?? '', mark: true });
    last = match.index + match[0].length;
  }
  if (last < snippet.length) parts.push({ text: snippet.slice(last), mark: false });
  return parts;
}

export function formatDate(iso: string): string {
  const date = new Date(iso);
  const sameYear = date.getFullYear() === new Date().getFullYear();
  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    ...(sameYear ? {} : { year: 'numeric' }),
  });
}
