// What a spoken sentence asks for (SPEC §11 "full voice navigation"), kept pure so it's unit-tested.
// App commands (views, panels, modes, memos, dictation, stop) are handled here; "go to / open / show …" goes to
// Core's recall fast path; anything else is a question for Core (chat), answered out loud.
import type { Panel, View } from '../state/store';

export type VoiceMode = 'push_to_talk' | 'wake' | 'continuous';

export type VoiceCommand =
  | { kind: 'stop' }
  | { kind: 'mode'; mode: VoiceMode }
  | { kind: 'memo'; action: 'start' | 'stop' | 'cancel' }
  | { kind: 'dictation'; on: boolean }
  | { kind: 'view'; view: View }
  | { kind: 'panel'; panel: Panel }
  | { kind: 'chat'; open: boolean }
  | { kind: 'zen' }
  | { kind: 'home' }
  | { kind: 'zoom'; direction: 'in' | 'out' }
  | { kind: 'back' }
  | { kind: 'kill' }
  | { kind: 'approve'; approve: boolean }
  | { kind: 'read' }
  | { kind: 'mic_off' }
  | { kind: 'recall'; text: string }
  | { kind: 'ask'; text: string };

/** Whisper writes "Take me to Ember Wolf." — drop the final punctuation and the filler a command doesn't need. */
export function normalize(text: string): string {
  return text
    .trim()
    .replace(/^(?:um+|uh+|okay|ok|so|please)[,\s]+/i, '')
    .replace(/[\s,]*(?:please|thanks|thank you)?[.!?…]*$/i, '')
    .replace(/\s+/g, ' ')
    .trim();
}

const PANELS: Record<string, Panel> = {
  context: 'context',
  details: 'context',
  vault: 'vault',
  agents: 'agents',
  agent: 'agents',
  tasks: 'agents',
  research: 'research',
  forge: 'forge',
  safety: 'safety',
  system: 'system',
  settings: 'system',
  voice: 'voice',
  'voice settings': 'voice',
};

const RULES: Array<[RegExp, (m: RegExpMatchArray) => VoiceCommand]> = [
  [
    /^(?:stop|stop talking|be quiet|quiet|shush|cancel that|never mind|nevermind|that's enough)$/i,
    () => ({ kind: 'stop' }),
  ],
  [/^(?:engage (?:the )?kill switch|kill switch|emergency stop)$/i, () => ({ kind: 'kill' })],
  [/^(?:turn off|mute|stop) (?:the )?(?:mic|microphone|listening)$/i, () => ({ kind: 'mic_off' })],
  [
    /^(?:approve|approve it|approved|yes,? (?:do it|go ahead)|go ahead|allow it)$/i,
    () => ({ kind: 'approve', approve: true }),
  ],
  [
    /^(?:deny|deny it|decline|decline it|reject|reject it|don't|no,? don't(?: do it)?)$/i,
    () => ({ kind: 'approve', approve: false }),
  ],
  [
    /^(?:read it|read (?:it|this|that) (?:to me|aloud|out loud)|what does it say)$/i,
    () => ({ kind: 'read' }),
  ],
  [
    /^(?:(?:switch to |use |start )?continuous(?: mode| listening)?|keep listening)$/i,
    () => ({ kind: 'mode', mode: 'continuous' }),
  ],
  [/^(?:(?:switch to |use )?wake ?word(?: mode)?|stop listening)$/i, () => ({ kind: 'mode', mode: 'wake' })],
  [/^(?:switch to |use )?push to talk(?: mode)?$/i, () => ({ kind: 'mode', mode: 'push_to_talk' })],
  [
    /^(?:take|record|start)(?: a)?(?: new)? (?:voice )?(?:memo|note by voice|voice note)$/i,
    () => ({ kind: 'memo', action: 'start' }),
  ],
  [
    /^(?:stop|save|end|finish)(?: the)? (?:memo|recording|voice memo)$/i,
    () => ({ kind: 'memo', action: 'stop' }),
  ],
  [
    /^(?:discard|delete|cancel|throw away)(?: the)? (?:memo|recording)$/i,
    () => ({ kind: 'memo', action: 'cancel' }),
  ],
  [/^(?:start )?dictat(?:e|ion)(?: mode)?$|^start dictating$/i, () => ({ kind: 'dictation', on: true })],
  [/^(?:stop|end) dictat(?:ion|ing)$/i, () => ({ kind: 'dictation', on: false })],
  [
    /^(?:show |switch to |open )?(?:the )?(grid|list|universe)(?: view)?$/i,
    (m) => ({ kind: 'view', view: m[1]!.toLowerCase() as View }),
  ],
  [/^(?:open|show)(?: the)? chat$/i, () => ({ kind: 'chat', open: true })],
  [/^(?:close|hide)(?: the)? chat$/i, () => ({ kind: 'chat', open: false })],
  [/^(?:toggle |enter |exit |leave )?zen(?: mode)?$/i, () => ({ kind: 'zen' })],
  [
    /^(?:go |fly |take me )?home$|^(?:show|zoom out to) (?:everything|the whole universe)$/i,
    () => ({ kind: 'home' }),
  ],
  [
    /^zoom (in|out)$|^(?:get )?(closer)$|^(further|farther) out$/i,
    (m) => ({ kind: 'zoom', direction: m[1]?.toLowerCase() === 'in' || m[2] ? 'in' : 'out' }),
  ],
  [/^(?:go )?back$|^(?:close|dismiss)(?: (?:this|that|it|the viewer))?$/i, () => ({ kind: 'back' })],
];

export function parseVoiceCommand(raw: string): VoiceCommand | null {
  const text = normalize(raw);
  if (!text) return null;
  for (const [pattern, build] of RULES) {
    const m = text.match(pattern);
    if (m) return build(m);
  }
  const panel = text.match(/^(?:open|show)(?: me)?(?: the)? (.+?)(?: panel| tab)?$/i);
  if (panel) {
    const target = PANELS[panel[1]!.toLowerCase()];
    if (target) return { kind: 'panel', panel: target };
  }
  // Core's recall grammar: go to / take me to / open / play / show / find … (no LLM, < 300 ms).
  if (
    /^(?:go to|goto|take me to|jump to|switch to|open|play|pull up|bring up|launch|show|list|find|search for|search|look for)\s+\S/i.test(
      text,
    )
  ) {
    return { kind: 'recall', text };
  }
  return { kind: 'ask', text };
}

/** Sentences as they stream in: speak each one as soon as it's complete (first audio sooner). */
export function splitSentences(buffer: string): { done: string[]; rest: string } {
  const done: string[] = [];
  const re = /[^.!?\n]*[.!?]+(?=\s|$)|[^\n]*\n/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(buffer)) !== null) {
    if (m.index + m[0].length === buffer.length && !/\s$/.test(m[0]) && !m[0].endsWith('\n')) break; // may continue
    const sentence = m[0].trim();
    if (sentence) done.push(sentence);
    last = m.index + m[0].length;
  }
  return { done, rest: buffer.slice(last).trimStart() };
}

/** Markdown the model writes ("**bold**", "[1]", "- item") reads badly out loud. */
export function speakable(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, ' (code omitted) ')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[(\d+)\]/g, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/https?:\/\/\S+/g, 'a link')
    .replace(/[*_#>]+/g, '')
    .replace(/^\s*[-•]\s+/gm, '')
    .replace(/\s+/g, ' ')
    .trim();
}
