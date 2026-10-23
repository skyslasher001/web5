import { describe, expect, it } from 'vitest';
import { draftAfterSave, GoalQueue, keepAttribute, markdownToHtml } from './viewerUtils';

describe('wikilinks in Markdown', () => {
  it('become links the viewer follows, with an optional label', () => {
    expect(markdownToHtml('See [[Water Notes]] and [[Ember Wolf|the business]].')).toBe(
      '<p>See <a href="#" data-wikilink="Water Notes">Water Notes</a> and ' +
        '<a href="#" data-wikilink="Ember Wolf">the business</a>.</p>\n',
    );
  });

  it('stay literal inside code, and are escaped', () => {
    const html = markdownToHtml('`[[Not a link]]`\n\n```\n[[Also not]]\n```\n\n[[A|a <b> "c"]]');
    expect(html).toContain('<code>[[Not a link]]</code>');
    expect(html).toContain('[[Also not]]');
    expect(html).not.toContain('data-wikilink="Not a link"');
    expect(html).toContain('<a href="#" data-wikilink="A">a &lt;b&gt; &quot;c&quot;</a>');
  });
});

describe('saving a note', () => {
  it('keeps what was typed while the save was in flight', () => {
    expect(draftAfterSave('hello', 'hello')).toBeNull();
    expect(draftAfterSave('hello world', 'hello')).toBe('hello world');
    expect(draftAfterSave(null, 'hello')).toBeNull();
  });
});

describe('sanitizing a note', () => {
  // DOMPurify calls keepAttribute for every attribute it would keep (the uponSanitizeAttribute hook).
  it('drops media URLs that would load from another machine', () => {
    expect(keepAttribute('img', 'src', 'https://tracker.example/pixel.png')).toBe(false);
    expect(keepAttribute('img', 'src', ' HTTP://x.example/a.png')).toBe(false);
    expect(keepAttribute('img', 'src', 'ht\ttps://x.example/a.png')).toBe(false); // the parser drops tabs
    expect(keepAttribute('img', 'src', '//x.example/a.png')).toBe(false); // protocol-relative
    expect(keepAttribute('img', 'src', '\\\\server\\share\\a.png')).toBe(false); // a Windows share
    expect(keepAttribute('img', 'src', 'file://server/share/a.png')).toBe(false);
    expect(keepAttribute('video', 'poster', 'https://x.example/p.jpg')).toBe(false);
    expect(keepAttribute('img', 'srcset', 'a.png 1x, https://x.example/b.png 2x')).toBe(false);
    expect(keepAttribute('image', 'xlink:href', 'https://x.example/a.svg')).toBe(false);
    expect(keepAttribute('td', 'background', 'https://x.example/bg.png')).toBe(false);
    expect(keepAttribute('p', 'style', 'background: url(https://x.example/a.png)')).toBe(false);
    expect(keepAttribute('p', 'style', 'background: u\\72l(https://x.example/a.png)')).toBe(false);
  });

  it('keeps local media, ordinary links and plain styles', () => {
    expect(keepAttribute('img', 'src', 'blob:app://universe/1234')).toBe(true);
    expect(keepAttribute('img', 'src', 'data:image/png;base64,iVBORw0KGgo=')).toBe(true);
    expect(keepAttribute('img', 'src', 'attachments/photo.png')).toBe(true);
    expect(keepAttribute('img', 'srcset', 'data:image/png;base64,AA,BB 1x, small.png 2x')).toBe(true);
    expect(keepAttribute('a', 'href', 'https://example.com')).toBe(true); // a click, not a load
    expect(keepAttribute('p', 'style', 'color: rgb(1, 2, 3)')).toBe(true);
    expect(keepAttribute('p', 'title', 'https://example.com')).toBe(true);
  });
});

describe("editing a galaxy's goals", () => {
  it('builds each quick edit on the last one, saving them in order', async () => {
    const sent: string[][] = [];
    let settled = 0;
    const queue = new GoalQueue(
      async (goals) => {
        await new Promise((r) => setTimeout(r, 5));
        sent.push(goals.map((g) => g.text));
      },
      () => settled++,
    );
    const server = [{ text: 'a', done: false }]; // the project as fetched: it doesn't change until a refetch
    queue.edit(server, (g) => [...g, { text: 'b', done: false }]);
    const shown = queue.edit(server, (g) => [...g, { text: 'c', done: false }]); // typed before the save landed
    expect(shown.map((g) => g.text)).toEqual(['a', 'b', 'c']);
    await new Promise((r) => setTimeout(r, 30));
    expect(sent).toEqual([
      ['a', 'b'],
      ['a', 'b', 'c'],
    ]);
    expect(settled).toBe(1);
    // Once settled, the next edit starts from the project as fetched again.
    expect(queue.edit([{ text: 'z', done: true }], (g) => g).map((g) => g.text)).toEqual(['z']);
  });

  it('settles after a failed save, so the fetched goals show again', async () => {
    let settled = 0;
    const queue = new GoalQueue(
      () => Promise.reject(new Error('Core is restarting')),
      () => settled++,
    );
    queue.edit([], (g) => [...g, { text: 'a', done: false }]);
    await new Promise((r) => setTimeout(r, 0));
    expect(settled).toBe(1);
  });
});
