import { describe, expect, it } from 'vitest';
import { draftAfterSave, markdownToHtml } from './viewerUtils';

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
