// What happens to what you say (SPEC §11): app commands run here, "go to / open / show …" takes Core's recall fast
// path (no LLM), and anything else is a question for Core whose streamed answer is spoken sentence by sentence in
// the agent's own voice. Also dictation into the focused text field, voice memos, and the mic switch.
import type { CoreEvent, RecallResult } from '@universe/shared-types';
import { useUniverse } from '../state/store';
import { rig } from '../universe/scene/helpers';
import { NOTCH } from '../universe/scene/zoom';
import { ApiError, type CoreApi } from './api';
import { bridge } from './bridge';
import { VoiceClient, useVoice, type VoiceEvent } from './voiceClient';
import { parseVoiceCommand, speakable, splitSentences, type VoiceMode } from './voiceCommands';

const MODE_NAMES: Record<VoiceMode, string> = {
  push_to_talk: 'Push to talk.',
  wake: 'Wake word mode. Say "Hey Universe" first.',
  continuous: "Continuous mode. I'm listening.",
};
const TRANSIT_S = 0.15; // the final event's trip from the voice process to here

interface Answer {
  conversationId: string;
  agentId: string;
  buffer: string;
  text: string;
  silenced: boolean;
}

/** Insert text where the caret is, in any text field (React sees a normal input event). */
export function dictate(text: string): boolean {
  const el = document.activeElement as HTMLElement | null;
  const editable =
    !!el &&
    (el.tagName === 'TEXTAREA' ||
      (el.tagName === 'INPUT' && (el as HTMLInputElement).type === 'text') ||
      el.isContentEditable);
  if (!editable) return false;
  let before = '';
  if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
    const field = el as HTMLTextAreaElement;
    before = field.value.slice(0, field.selectionStart ?? field.value.length);
  }
  const spaced = before && !/\s$/.test(before) ? ` ${text}` : text;
  if (!document.execCommand('insertText', false, spaced)) {
    const field = el as HTMLTextAreaElement;
    field.setRangeText(spaced, field.selectionStart ?? 0, field.selectionEnd ?? 0, 'end');
    field.dispatchEvent(new Event('input', { bubbles: true }));
  }
  return true;
}

export class Voice {
  readonly client: VoiceClient;
  private voices: Record<string, string> = {};
  private defaultVoice = 'af_heart';
  private speed = 1;
  private conversationId: string | null = null;
  private answer: Answer | null = null;

  constructor(private readonly api: CoreApi) {
    this.client = new VoiceClient(async () => {
      const base = useUniverse.getState().config?.wsUrl ?? '';
      return `${base}/voice?ticket=${encodeURIComponent((await api.wsTicket()).ticket)}`;
    });
    this.client.on((e) => void this.onVoiceEvent(e));
  }

  // ---------- on / off ----------

  /** Start the voice process and connect (speaking works even without the mic). */
  async connect(): Promise<void> {
    const status = await this.api.voiceStart();
    if (status.state !== 'ready') throw new Error(status.reason ?? 'Voice did not start');
    this.defaultVoice = status.settings.voice;
    this.speed = status.settings.speed;
    await this.refreshVoices();
    await this.client.connect();
    this.client.setMode(status.settings.mode as VoiceMode);
  }

  async refreshVoices(): Promise<void> {
    const v = await this.api.voices();
    this.defaultVoice = v.default;
    this.voices = Object.fromEntries(v.agents.map((a) => [a.agent_id, a.voice]));
  }

  setSpeed(speed: number): void {
    this.speed = speed;
  }

  /** The orb's mic button: main decides (protected consent); the mic opens only if it says yes. */
  async toggleMic(): Promise<void> {
    const store = useVoice.getState();
    if (store.micOn) return this.micOff();
    const consent = await bridge().setMicConsent(true);
    store.set({ consent });
    if (!consent.available || !consent.mic) {
      const reason = consent.reason ?? 'The microphone is off.';
      store.set({ error: reason });
      useUniverse.getState().addNotice('warn', reason);
      return;
    }
    try {
      if (!this.client.connected) await this.connect();
      await this.client.startMic();
      store.set({ error: null });
    } catch (err) {
      this.client.stopMic(); // nothing half-open stays behind
      await bridge().setMicConsent(false);
      throw err;
    }
  }

  async micOff(): Promise<void> {
    this.client.stopMic();
    useVoice.getState().set({ consent: await bridge().setMicConsent(false), dictation: false });
  }

  /** Consent was withdrawn (kill switch, tray, another window): close the mic now. */
  consentChanged(mic: boolean): void {
    if (!mic) this.client.stopMic(); // also cancels a mic that is still starting
  }

  shutdown(): void {
    this.client.disconnect();
  }

  // ---------- speaking ----------

  voiceFor(agentId: string): string {
    return this.voices[agentId] ?? this.defaultVoice;
  }

  say(text: string, agentId = 'core'): void {
    const spoken = speakable(text);
    if (!spoken) return;
    useVoice.getState().set({ reply: text });
    if (this.client.connected) this.client.speak(spoken, this.voiceFor(agentId), this.speed);
  }

  stop(): void {
    this.client.stopSpeaking();
    if (this.answer) this.answer.silenced = true;
  }

  // ---------- what you said ----------

  private async onVoiceEvent(e: VoiceEvent): Promise<void> {
    if (e.type === 'barge_in' && this.answer) this.answer.silenced = true;
    if (e.type === 'memo_full') await this.finishMemo(0);
    if (e.type === 'closed') return this.socketClosed();
    if (e.type !== 'final') return;
    try {
      // Recorded since you finished that sentence: the utterance itself (its silence included) plus Whisper's time.
      const since = Number(e.audio_s ?? 0) + Number(e.stt_s ?? 0);
      await this.handle(String(e.text ?? ''), since);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      useVoice.getState().set({ error: message, state: 'idle' });
      this.say(`Sorry, ${message}`);
    }
  }

  /** Voice restarted (new settings, a model installed) or stopped: reconnect, or close the mic — never leave it
   *  open with nothing listening. */
  private async socketClosed(): Promise<void> {
    if (!useVoice.getState().micOn) return;
    try {
      await new Promise((r) => setTimeout(r, 500)); // a restart takes a moment
      const status = await this.api.voiceStatus();
      if (status.state === 'starting' || status.state === 'ready') {
        await this.connect();
        return;
      }
    } catch {
      // fall through: turn the mic off
    }
    await this.micOff();
    useVoice.getState().set({ error: 'Voice stopped, so the microphone was turned off.' });
  }

  async handle(text: string, spokenS = 0): Promise<void> {
    const store = useVoice.getState();
    const s = useUniverse.getState();
    const cmd = parseVoiceCommand(text);
    if (!cmd) return;
    if (store.memo) {
      // While recording, only memo commands count; everything else is the memo.
      if (cmd.kind === 'memo' && cmd.action === 'stop') await this.finishMemo(spokenS + TRANSIT_S);
      else if (cmd.kind === 'memo' && cmd.action === 'cancel') {
        this.client.cancelMemo();
        this.say('Memo discarded.');
      }
      return;
    }
    if (store.dictation && cmd.kind !== 'dictation' && cmd.kind !== 'stop') {
      if (!dictate(text.trim())) s.addNotice('info', 'Dictation: click into a text field first');
      return;
    }
    switch (cmd.kind) {
      case 'stop':
        this.stop();
        if (store.dictation) store.set({ dictation: false });
        if (this.answer) void this.api.cancelChat(this.answer.conversationId).catch(() => {});
        return;
      case 'kill':
        await bridge().setKillSwitch(true);
        return;
      case 'mic_off':
        await this.micOff();
        return;
      case 'approve':
        await this.decide(cmd.approve);
        return;
      case 'read':
        await this.read();
        return;
      case 'mode':
        this.client.setMode(cmd.mode);
        void this.api.voiceSettings({ mode: cmd.mode }).catch(() => {});
        this.say(MODE_NAMES[cmd.mode]);
        return;
      case 'memo':
        if (cmd.action === 'start') {
          this.client.startMemo();
          s.addNotice('info', 'Recording a memo · say "save the memo" when you\'re done');
        }
        return;
      case 'dictation':
        store.set({ dictation: cmd.on });
        this.say(cmd.on ? 'Dictating.' : 'Dictation off.');
        return;
      case 'view':
        s.setView(cmd.view);
        return;
      case 'panel':
        s.setPanel(cmd.panel);
        return;
      case 'chat':
        s.setChatOpen(cmd.open);
        return;
      case 'zen':
        s.toggleZen();
        return;
      case 'home':
        s.setView('universe');
        s.flyHome();
        return;
      case 'zoom':
        s.setView('universe');
        rig.zoomBy(cmd.direction === 'out' ? NOTCH ** 4 : 1 / NOTCH ** 4);
        return;
      case 'back':
        if (s.viewerItemId || s.dashboardProjectId) s.closeViewer();
        else if (!s.zoomOut()) s.selectItem(null);
        return;
      case 'recall':
        await this.recall(cmd.text);
        return;
      case 'ask':
        await this.ask(cmd.text);
        return;
    }
  }

  /** "Approve" / "deny": the oldest waiting approval. Core refuses high-risk ones by voice (they take a click). */
  private async decide(approve: boolean): Promise<void> {
    const [first] = await this.api.approvals();
    if (!first) {
      this.say('Nothing is waiting for you.');
      return;
    }
    try {
      await this.api.decideApproval(first.id, approve, false, 'voice');
      this.say(approve ? 'Approved.' : 'Declined.');
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        useUniverse.getState().setPanel('agents');
        this.say("That one is high risk: it needs a click. It's in the approvals tray.");
      } else throw err;
    }
  }

  /** "Read it": the open (or selected) item's text, the first few sentences. */
  private async read(): Promise<void> {
    const s = useUniverse.getState();
    const id = s.viewerItemId ?? s.selectedItemId;
    if (!id) {
      this.say('Open something first.');
      return;
    }
    const text = (await this.api.itemText(id, 1200)).text.trim();
    this.say(
      text
        ? text
            .split(/(?<=[.!?])\s+/)
            .slice(0, 6)
            .join(' ')
        : 'It has no text to read.',
    );
  }

  private async recall(text: string): Promise<void> {
    const result: RecallResult = await this.api.recall(text);
    const s = useUniverse.getState();
    if (result.action === 'show_project' && result.target_id) {
      const project = (await this.api.projects()).find((p) => p.id === result.target_id);
      if (s.view !== 'universe') s.setView('universe');
      s.selectProject(result.target_id);
      this.say(`Flying to ${project?.name ?? 'the galaxy'}.`, 'navigator');
      return;
    }
    const top = result.hits[0];
    if (result.action === 'open_item' && result.target_id && top) {
      s.openViewer(result.target_id);
      this.say(`Here's ${top.item.title}.`, 'navigator');
      return;
    }
    if (result.intent === 'search' && !top) return this.ask(text); // not a navigation after all
    if (!top) {
      this.say("I couldn't find that.", 'navigator');
      return;
    }
    s.setQuery(result.parsed.text || text);
    s.focusResults();
    if (result.hits.length === 1) s.selectItem(top.item.id);
    const n = result.hits.length;
    this.say(
      n === 1 ? `I found ${top.item.title}.` : `I found ${n} results. The first is ${top.item.title}.`,
      'navigator',
    );
  }

  private async ask(text: string): Promise<void> {
    this.conversationId ??= crypto.randomUUID();
    this.answer = {
      conversationId: this.conversationId,
      agentId: 'core',
      buffer: '',
      text: '',
      silenced: false,
    };
    useVoice.getState().set({ state: 'thinking', reply: '' });
    await this.api.sendChat(text, this.conversationId);
  }

  /** Core's chat events: speak the answer as it streams (first sentence out as soon as it's complete). */
  onCoreEvent(event: CoreEvent): void {
    const p = event.payload as Record<string, unknown>;
    if (event.type === 'approval.requested') {
      if (!this.client.connected) return; // only when you're using voice
      const who = String(p.agent_id ?? 'An agent');
      const name = who.charAt(0).toUpperCase() + who.slice(1);
      const how = p.risk === 'high' ? 'It is high risk: answer it on screen.' : 'Say approve or deny.';
      const what = String(p.summary ?? p.tool ?? 'do something');
      this.say(`${name} asks to ${what.charAt(0).toLowerCase()}${what.slice(1)}. ${how}`, who);
      return;
    }
    const a = this.answer;
    if (!a || p.conversation_id !== a.conversationId) return;
    if (event.type === 'chat.started') {
      a.agentId = String(p.agent_id ?? 'core');
    } else if (event.type === 'chat.token') {
      a.buffer += String(p.delta ?? '');
      a.text += String(p.delta ?? '');
      useVoice.getState().set({ reply: a.text });
      const { done, rest } = splitSentences(a.buffer);
      a.buffer = rest;
      if (!a.silenced) done.forEach((sentence) => this.speakPart(sentence, a.agentId));
    } else if (event.type === 'chat.completed' || event.type === 'chat.cancelled') {
      if (!a.silenced && event.type === 'chat.completed') this.speakPart(a.buffer, a.agentId);
      this.answer = null;
      if (!this.client.speaking) useVoice.getState().set({ state: 'idle' });
    } else if (event.type === 'chat.failed') {
      this.answer = null;
      this.say(`That didn't work: ${String(p.error ?? 'the model failed')}`);
    }
  }

  private speakPart(text: string, agentId: string): void {
    const spoken = speakable(text);
    if (spoken && this.client.connected) this.client.speak(spoken, this.voiceFor(agentId), this.speed);
  }

  // ---------- memos ----------

  async startMemo(): Promise<void> {
    if (!useVoice.getState().micOn) await this.toggleMic();
    if (useVoice.getState().micOn) this.client.startMemo();
  }

  async finishMemo(trimS: number): Promise<void> {
    const wav = this.client.finishMemo(trimS);
    if (!wav) {
      this.say('That memo was empty.');
      return;
    }
    const saved = await this.api.saveMemo(wav);
    useUniverse.getState().addNotice('good', 'Memo saved to the vault · it will be transcribed');
    this.say(saved.status === 'duplicate' ? 'You already saved that memo.' : 'Memo saved.');
  }
}

let instance: Voice | null = null;

export function voice(api?: CoreApi): Voice | null {
  if (!instance && api) instance = new Voice(api);
  return instance;
}
