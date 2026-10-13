import '@fontsource-variable/inter';
import '@fontsource-variable/jetbrains-mono';
import '@fontsource-variable/space-grotesk';
import './styles.css';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});
// Thumbnails are object URLs held in the cache: free each one when its entry is dropped.
queryClient.getQueryCache().subscribe((event) => {
  const { queryKey, state } = event.query;
  if (event.type === 'removed' && queryKey[0] === 'thumb' && typeof state.data === 'string') {
    URL.revokeObjectURL(state.data);
  }
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
