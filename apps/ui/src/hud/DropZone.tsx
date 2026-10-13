// Drag-drop anywhere in the window (SPEC §5): files and folders are copied into the vault.
import { Upload } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useApi } from '../lib/api-context';
import { useProjects } from '../lib/queries';
import { ingestDropped } from '../lib/vaultActions';
import { useUniverse } from '../state/store';

function hasFiles(e: DragEvent): boolean {
  return !!e.dataTransfer && Array.from(e.dataTransfer.types).includes('Files');
}

export function DropZone() {
  const api = useApi();
  const projects = useProjects();
  const projectId = useUniverse((s) => s.selectedProjectId);
  const [over, setOver] = useState(false);
  const depth = useRef(0);
  const project = projects.data?.find((p) => p.id === projectId);

  useEffect(() => {
    const enter = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth.current += 1;
      setOver(true);
    };
    const leave = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setOver(false);
    };
    const overHandler = (e: DragEvent) => {
      if (hasFiles(e)) e.preventDefault(); // allow the drop
    };
    const drop = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth.current = 0;
      setOver(false);
      const files = Array.from(e.dataTransfer?.files ?? []);
      void ingestDropped(api, files, useUniverse.getState().selectedProjectId);
    };
    window.addEventListener('dragenter', enter);
    window.addEventListener('dragleave', leave);
    window.addEventListener('dragover', overHandler);
    window.addEventListener('drop', drop);
    return () => {
      window.removeEventListener('dragenter', enter);
      window.removeEventListener('dragleave', leave);
      window.removeEventListener('dragover', overHandler);
      window.removeEventListener('drop', drop);
    };
  }, [api]);

  if (!over) return null;
  return (
    <div
      className="pointer-events-none fixed inset-3 flex items-center justify-center rounded-2xl border-2 border-dashed border-accent/60 bg-space-0/70"
      style={{ zIndex: 'var(--z-dialog)' }}
      aria-live="polite"
    >
      <div className="glass-strong flex flex-col items-center gap-2 px-10 py-8 text-center">
        <Upload className="size-8 text-accent" aria-hidden />
        <p className="font-display text-lg">Drop to add to your vault</p>
        <p className="text-xs text-ink-3">
          Copied in, never moved{project ? ` · joins ${project.name}` : ''}
        </p>
      </div>
    </div>
  );
}
