import { tokens } from '@universe/design-tokens';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { History, MessageSquarePlus, Send, Square, X } from 'lucide-react';
import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { ApiError } from '../lib/api';
import { attempt } from '../lib/attempt';
import { useApi } from '../lib/api-context';
import { useModels } from '../lib/queries';
import { fromStored, type ChatMessage } from '../state/reducers';
import { useUniverse } from '../state/store';
import { CopyButton, Kbd } from './ui';

function Orb() {
  const open = useUniverse((s) => s.chatOpen);
  const setOpen = useUniverse((s) => s.setChatOpen);
  const activity = useUniverse((s) => s.agentActivity.core ?? 'idle');
  const online = useUniverse((s) => s.connection === 'online');
  const color = !online
    ? tokens.color.slate
    : activity === 'error'
      ? tokens.color.danger
      : tokens.color.accent;
  const step = useUniverse((s) => s.agentSteps.core);
  const busy = activity === 'thinking' || activity === 'replying';
  const label = !online
    ? 'Core offline'
    : busy
      ? activity === 'thinking'
        ? (step ?? 'Thinking…')
        : 'Replying…'
      : 'Chat with Core';
  return (
    <div className="flex flex-col items-center gap-2">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-label={open ? 'Close chat' : 'Open chat with Core'}
        aria-expanded={open}
        data-testid="orb"
        className="no-drag relative grid size-16 place-items-center rounded-full transition-transform duration-200 hover:scale-105"
      >
        <span
          className="orb-breathe absolute inset-0 rounded-full"
          style={{ background: `radial-gradient(circle, ${color}55, transparent 70%)` }}
        />
        {busy && (
          <span
            className="orb-spin absolute inset-1 rounded-full border-2 border-transparent"
            style={{ borderTopColor: color, borderRightColor: `${color}66` }}
          />
        )}
        <span
          className="relative size-9 rounded-full border"
          style={{
            borderColor: `${color}aa`,
            background: `radial-gradient(circle at 35% 30%, ${color}, ${tokens.color.space[2]} 75%)`,
            boxShadow: `0 0 24px ${color}66`,
          }}
        />
      </button>
      <span className="flex items-center gap-2 text-xs text-ink-3">
        {label} <Kbd>C</Kbd>
      </span>
    </div>
  );
}

function MessageView({ m }: { m: ChatMessage }) {
  const step = useUniverse((s) => s.agentSteps.core);
  const selectTask = useUniverse((s) => s.selectTask);
  if (m.role === 'user') {
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-lg rounded-br-sm bg-space-3 px-3 py-2 text-sm whitespace-pre-wrap text-ink-1 select-text">
          {m.content}
        </p>
      </div>
    );
  }
  const meta = [
    m.model,
    m.firstTokenMs != null ? `first token ${m.firstTokenMs} ms` : null,
    m.status === 'cancelled' ? 'stopped' : null,
  ]
    .filter(Boolean)
    .join(' · ');
  return (
    <div className="space-y-1" data-testid="assistant-message" data-status={m.status}>
      <p className="text-sm leading-relaxed whitespace-pre-wrap text-ink-1 select-text">
        {m.content}
        {m.status === 'streaming' && (
          <span className="caret ml-0.5 inline-block h-4 w-1.5 translate-y-0.5 bg-accent" aria-hidden />
        )}
      </p>
      {m.status === 'streaming' && step && (
        <p className="text-xs text-ink-3" data-testid="agent-progress">
          {step}
        </p>
      )}
      {m.error && (
        <div role="alert" className="rounded-md border border-danger/30 p-2 text-xs">
          <p className="text-danger">{m.error.error}</p>
          {m.error.hint && (
            <p className="mt-1 flex items-center justify-between gap-2 font-mono text-ink-2">
              {m.error.hint}
              {m.error.hint.startsWith('Run: ') && <CopyButton text={m.error.hint.slice(5)} />}
            </p>
          )}
        </div>
      )}
      {(meta || m.taskId) && (
        <p className="flex items-center gap-2 font-mono text-[11px] text-ink-3">
          {meta}
          {m.taskId && (
            <button
              type="button"
              onClick={() => selectTask(m.taskId)}
              className="font-sans hover:text-accent"
              data-testid="view-trace"
            >
              View trace
            </button>
          )}
        </p>
      )}
    </div>
  );
}

function ChatPanel() {
  const api = useApi();
  const models = useModels();
  const { conversationId, messages, newConversation, openConversation, setChatOpen } = useUniverse();
  const online = useUniverse((s) => s.connection === 'online');
  const safeMode = useUniverse((s) => s.desktop?.supervisor?.safe_mode.active ?? false);
  const [text, setText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<{ id: string; title: string }[]>([]);
  const scroller = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const streaming = messages.some((m) => m.status === 'streaming');
  const blocked = !online ? 'Core is offline.' : safeMode ? 'Agents are disabled in safe mode.' : null;

  useEffect(() => input.current?.focus(), []);
  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [messages]);

  const send = async () => {
    const body = text.trim();
    if (!body || streaming || blocked) return;
    setError(null);
    const id = conversationId ?? newConversation();
    setText('');
    try {
      await api.sendChat(body, id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setText(body);
    }
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  };

  return (
    <motion.section
      aria-label="Chat with Core"
      initial={{ opacity: 0, y: 16, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 16, scale: 0.98 }}
      transition={{ type: 'spring', stiffness: 260, damping: 28 }}
      className="glass-strong pointer-events-auto mb-3 flex max-h-[min(60vh,40rem)] w-[min(40rem,calc(100vw-48rem))] min-w-[26rem] flex-col"
      data-testid="chat-panel"
    >
      <header className="flex items-center gap-2 border-b border-hairline-1 px-4 py-3">
        <h2 className="flex-1 font-display text-sm font-semibold">Core</h2>
        <button
          type="button"
          title="Recent conversations"
          onClick={() => {
            setHistoryOpen(!historyOpen);
            if (!historyOpen)
              attempt(
                'Loading conversations',
                api.conversations().then((c) => setHistory(c.map(({ id, title }) => ({ id, title })))),
              );
          }}
          className="rounded-md p-1.5 text-ink-3 hover:text-ink-1"
        >
          <History className="size-4" aria-label="Recent conversations" />
        </button>
        <button
          type="button"
          title="New chat"
          onClick={() => newConversation()}
          className="rounded-md p-1.5 text-ink-3 hover:text-ink-1"
        >
          <MessageSquarePlus className="size-4" aria-label="New chat" />
        </button>
        <button
          type="button"
          title="Close (Esc)"
          onClick={() => setChatOpen(false)}
          className="rounded-md p-1.5 text-ink-3 hover:text-ink-1"
        >
          <X className="size-4" aria-label="Close chat" />
        </button>
      </header>
      {historyOpen && (
        <ul className="max-h-48 overflow-y-auto border-b border-hairline-1 p-2">
          {history.length === 0 && <li className="px-2 py-1 text-xs text-ink-3">No conversations yet.</li>}
          {history.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                className="w-full truncate rounded-md px-2 py-1.5 text-left text-sm text-ink-2 hover:bg-space-3/60 hover:text-ink-1"
                onClick={() => {
                  setHistoryOpen(false);
                  attempt(
                    'Opening the conversation',
                    api.messages(c.id).then((m) => openConversation(c.id, m.map(fromStored))),
                  );
                }}
              >
                {c.title}
              </button>
            </li>
          ))}
        </ul>
      )}
      <div ref={scroller} className="flex-1 space-y-4 overflow-y-auto px-4 py-4" aria-live="polite">
        {messages.length === 0 && (
          <div className="space-y-2 py-6 text-center">
            <p className="font-display text-base text-ink-1">What are we working on?</p>
            <p className="text-xs text-ink-3">
              {models.data?.chat_model
                ? `Runs locally on ${models.data.chat_model}. Nothing leaves this machine.`
                : 'Install a chat model in Ollama to start (see System).'}
            </p>
          </div>
        )}
        {messages.map((m) => (
          <MessageView key={m.id} m={m} />
        ))}
      </div>
      <footer className="border-t border-hairline-1 p-3">
        {(error || blocked) && <p className="mb-2 text-xs text-danger">{error ?? blocked}</p>}
        <div className="flex items-end gap-2">
          <textarea
            ref={input}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKey}
            rows={1}
            placeholder="Message Core…  (Enter to send, Shift+Enter for a new line)"
            aria-label="Message Core"
            className="max-h-40 min-h-9 flex-1 resize-none rounded-md border border-hairline-2 bg-space-2/80 px-3 py-2 text-sm text-ink-1 placeholder:text-ink-3 focus:border-accent focus:outline-none"
          />
          {streaming ? (
            <button
              type="button"
              onClick={() => conversationId && attempt('Stopping the reply', api.cancelChat(conversationId))}
              className="grid size-9 place-items-center rounded-md border border-hairline-2 text-ink-2 hover:border-danger hover:text-danger"
              aria-label="Stop reply"
            >
              <Square className="size-3.5" aria-hidden />
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void send()}
              disabled={!text.trim() || !!blocked}
              className="grid size-9 place-items-center rounded-md bg-accent text-space-0 transition-opacity duration-150 disabled:opacity-30"
              aria-label="Send"
            >
              <Send className="size-4" aria-hidden />
            </button>
          )}
        </div>
      </footer>
    </motion.section>
  );
}

export function ChatDock() {
  const open = useUniverse((s) => s.chatOpen);
  const reduced = useReducedMotion();
  return (
    <div className="pointer-events-none absolute bottom-4 left-1/2 flex -translate-x-1/2 flex-col items-center">
      <AnimatePresence initial={!reduced}>{open && <ChatPanel />}</AnimatePresence>
      <div className="pointer-events-auto">
        <Orb />
      </div>
    </div>
  );
}
