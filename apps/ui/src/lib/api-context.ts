import { createContext, useContext } from 'react';
import type { CoreApi } from './api';

export const ApiContext = createContext<CoreApi | null>(null);

export function useApi(): CoreApi {
  const api = useContext(ApiContext);
  if (!api) throw new Error('useApi outside CoreProvider');
  return api;
}
