import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { modalOpen, typing } from '../lib/hotkeys';
import { useUniverse } from './store';

const confirm = vi.fn<(message: string) => boolean>();

beforeEach(() => {
  vi.stubGlobal('window', { confirm });
  useUniverse.setState({ viewerItemId: null, dashboardProjectId: null, viewerDirty: false, timeCut: null });
});

afterEach(() => {
  vi.unstubAllGlobals();
  confirm.mockReset();
});

describe('unsaved note edits', () => {
  it('ask before another item replaces the viewer (a wikilink or backlink click)', () => {
    useUniverse.getState().openViewer('a');
    useUniverse.getState().setViewerDirty(true);
    confirm.mockReturnValue(false);
    useUniverse.getState().openViewer('b');
    expect(useUniverse.getState().viewerItemId).toBe('a');
    expect(useUniverse.getState().viewerDirty).toBe(true);
    confirm.mockReturnValue(true);
    useUniverse.getState().openViewer('b');
    expect(useUniverse.getState().viewerItemId).toBe('b');
    expect(useUniverse.getState().viewerDirty).toBe(false);
  });

  it('ask before a dashboard replaces the viewer, and never when nothing is unsaved', () => {
    useUniverse.getState().openViewer('a');
    useUniverse.getState().setViewerDirty(true);
    confirm.mockReturnValue(false);
    useUniverse.getState().openDashboard('g');
    expect(useUniverse.getState().dashboardProjectId).toBeNull();
    useUniverse.getState().setViewerDirty(false);
    useUniverse.getState().openDashboard('g');
    expect(useUniverse.getState().dashboardProjectId).toBe('g');
    expect(confirm).toHaveBeenCalledTimes(1);
  });
});

describe('shortcuts', () => {
  it('leave dropdowns and fields alone, and stay off while a viewer is open', () => {
    expect(typing({ tagName: 'SELECT' } as unknown as EventTarget)).toBe(true);
    expect(typing({ tagName: 'TEXTAREA' } as unknown as EventTarget)).toBe(true);
    expect(typing({ tagName: 'DIV', isContentEditable: false } as unknown as EventTarget)).toBe(false);
    expect(modalOpen({ viewerItemId: 'a', dashboardProjectId: null })).toBe(true);
    expect(modalOpen({ viewerItemId: null, dashboardProjectId: 'g' })).toBe(true);
    expect(modalOpen({ viewerItemId: null, dashboardProjectId: null })).toBe(false);
  });
});

describe('time travel', () => {
  it('ends when you leave the Time layout, so no items stay hidden elsewhere', () => {
    useUniverse.getState().setLayout('time');
    useUniverse.getState().setTimeCut(1_600_000_000);
    useUniverse.getState().setLayout('time');
    expect(useUniverse.getState().timeCut).toBe(1_600_000_000);
    useUniverse.getState().setLayout('project');
    expect(useUniverse.getState().timeCut).toBeNull();
  });
});
