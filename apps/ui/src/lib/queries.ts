import { useQuery } from '@tanstack/react-query';
import { useUniverse } from '../state/store';
import { useApi } from './api-context';

export function useProjects() {
  const api = useApi();
  const version = useUniverse((s) => s.dataVersion);
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({
    queryKey: ['projects', version],
    queryFn: api.projects,
    enabled: online,
    staleTime: 60_000,
  });
}

export function useModels() {
  const api = useApi();
  const version = useUniverse((s) => s.dataVersion);
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({
    queryKey: ['models', version],
    queryFn: api.models,
    enabled: online,
    refetchInterval: 15_000,
  });
}

export function useVitals(enabled: boolean) {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({
    queryKey: ['vitals'],
    queryFn: api.vitals,
    enabled: enabled && online,
    refetchInterval: 3_000,
  });
}

export function useHardware(enabled: boolean) {
  const api = useApi();
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({
    queryKey: ['hardware'],
    queryFn: api.hardware,
    enabled: enabled && online,
    staleTime: Infinity,
  });
}

export function useRecommendation(enabled: boolean) {
  const api = useApi();
  const version = useUniverse((s) => s.dataVersion);
  const online = useUniverse((s) => s.connection === 'online');
  return useQuery({
    queryKey: ['recommendation', version],
    queryFn: api.recommendation,
    enabled: enabled && online,
  });
}
