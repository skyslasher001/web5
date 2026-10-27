// "Ask Core about this": starts a chat with Core about the item in the viewer.
import { MessageSquare } from 'lucide-react';
import { useApi } from '../../lib/api-context';
import { attempt } from '../../lib/attempt';
import { useUniverse } from '../../state/store';
import { Button } from '../ui';

export function AskCore({ id, title, prompt }: { id: string; title: string; prompt?: string }) {
  const api = useApi();
  return (
    <Button
      onClick={() => {
        const s = useUniverse.getState();
        const conversation = s.newConversation();
        s.closeViewer();
        attempt(
          'Ask Core',
          api.sendChat(
            prompt ?? `Summarize “${title}” (item id ${id}) and tell me what stands out.`,
            conversation,
          ),
        );
      }}
      testid="ask-core"
    >
      <MessageSquare className="size-3.5" aria-hidden /> Ask Core about this
    </Button>
  );
}
