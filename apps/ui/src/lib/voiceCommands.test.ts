import { describe, expect, it } from 'vitest';
import { normalize, parseVoiceCommand, speakable, splitSentences } from './voiceCommands';

describe('normalize', () => {
  it('drops what Whisper adds around a command', () => {
    expect(normalize(' Take me to Ember Wolf. ')).toBe('Take me to Ember Wolf');
    expect(normalize('Um, open the grid view, please.')).toBe('open the grid view');
    expect(normalize('Stop!')).toBe('Stop');
  });
});

describe('parseVoiceCommand', () => {
  it.each([
    ['Stop.', { kind: 'stop' }],
    ['Never mind.', { kind: 'stop' }],
    ['Kill switch!', { kind: 'kill' }],
    ['Turn off the mic.', { kind: 'mic_off' }],
    ['Continuous mode.', { kind: 'mode', mode: 'continuous' }],
    ['Switch to push to talk.', { kind: 'mode', mode: 'push_to_talk' }],
    ['Wake word mode', { kind: 'mode', mode: 'wake' }],
    ['Take a memo.', { kind: 'memo', action: 'start' }],
    ['Save the memo.', { kind: 'memo', action: 'stop' }],
    ['Discard the recording', { kind: 'memo', action: 'cancel' }],
    ['Start dictation.', { kind: 'dictation', on: true }],
    ['Stop dictating.', { kind: 'dictation', on: false }],
    ['Show the grid view.', { kind: 'view', view: 'grid' }],
    ['Universe view', { kind: 'view', view: 'universe' }],
    ['Open chat', { kind: 'chat', open: true }],
    ['Zen mode', { kind: 'zen' }],
    ['Go home.', { kind: 'home' }],
    ['Zoom in', { kind: 'zoom', direction: 'in' }],
    ['Zoom out.', { kind: 'zoom', direction: 'out' }],
    ['Go back', { kind: 'back' }],
    ['Open the agents panel.', { kind: 'panel', panel: 'agents' }],
    ['Show voice settings', { kind: 'panel', panel: 'voice' }],
  ])('%s', (text, expected) => {
    expect(parseVoiceCommand(text)).toEqual(expected);
  });

  it('sends navigation to the recall fast path, punctuation removed', () => {
    expect(parseVoiceCommand('Take me to Ember Wolf.')).toEqual({
      kind: 'recall',
      text: 'Take me to Ember Wolf',
    });
    expect(parseVoiceCommand('Show photos from the lake.')).toEqual({
      kind: 'recall',
      text: 'Show photos from the lake',
    });
    expect(parseVoiceCommand('Play the song I made in March.')).toEqual({
      kind: 'recall',
      text: 'Play the song I made in March',
    });
    // "Open the grid" is a view, but "open the lease" is an item.
    expect(parseVoiceCommand('Open the lease')).toEqual({ kind: 'recall', text: 'Open the lease' });
  });

  it('asks Core everything else', () => {
    expect(parseVoiceCommand('What did I decide about the bridge?')).toEqual({
      kind: 'ask',
      text: 'What did I decide about the bridge',
    });
    expect(parseVoiceCommand('Forge, what broke?')).toEqual({ kind: 'ask', text: 'Forge, what broke' });
    expect(parseVoiceCommand('   ')).toBeNull();
  });
});

describe('splitSentences', () => {
  it('releases each finished sentence and keeps the tail', () => {
    expect(splitSentences('Flying to Ember Wolf. It has twelve')).toEqual({
      done: ['Flying to Ember Wolf.'],
      rest: 'It has twelve',
    });
    expect(splitSentences('One. Two! Three? ')).toEqual({ done: ['One.', 'Two!', 'Three?'], rest: '' });
  });

  it("doesn't cut a number or a sentence still streaming", () => {
    expect(splitSentences('It costs 4.5')).toEqual({ done: [], rest: 'It costs 4.5' });
    expect(splitSentences('Done.')).toEqual({ done: [], rest: 'Done.' }); // more may follow; flushed at the end
  });
});

describe('speakable', () => {
  it('reads markdown and citations naturally', () => {
    expect(speakable('**Ember Wolf** has [12 items](app://x) [1].\n- one\n- two')).toBe(
      'Ember Wolf has 12 items . one two',
    );
    expect(speakable('See https://example.com for `code`.')).toBe('See a link for code.');
  });
});
