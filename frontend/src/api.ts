import type {
  DownloadRecord,
  Publication,
  PublicationInput,
  Release,
  SearchResponse,
  Settings,
  SystemStatus,
  TestResult,
} from './types';

const BASE = '/api/v1';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });

  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) {
        detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      /* keep the status text */
    }
    throw new Error(detail);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  system: {
    status: () => request<SystemStatus>('/system/status'),
  },

  publications: {
    list: () => request<Publication[]>('/publications'),
    get: (id: number) => request<Publication>(`/publications/${id}`),
    create: (data: PublicationInput) =>
      request<Publication>('/publications', { method: 'POST', body: JSON.stringify(data) }),
    update: (id: number, data: Partial<PublicationInput>) =>
      request<Publication>(`/publications/${id}`, {
        method: 'PUT',
        body: JSON.stringify(data),
      }),
    remove: (id: number) =>
      request<void>(`/publications/${id}`, { method: 'DELETE' }),
    search: (id: number, extra = '') =>
      request<SearchResponse>(`/publications/${id}/search?extra=${encodeURIComponent(extra)}`, {
        method: 'POST',
      }),
    autoSearch: (id: number) =>
      request<DownloadRecord[]>(`/publications/${id}/auto-search`, { method: 'POST' }),
  },

  search: (query: string, categories = '') =>
    request<SearchResponse>(
      `/search?query=${encodeURIComponent(query)}&categories=${encodeURIComponent(categories)}`,
    ),

  queue: {
    list: () => request<{ records: DownloadRecord[] }>('/queue'),
    grab: (release: Release, publicationId: number | null) =>
      request<DownloadRecord>('/queue', {
        method: 'POST',
        body: JSON.stringify({ publication_id: publicationId, release }),
      }),
    remove: (id: number, deleteFiles = false) =>
      request<void>(`/queue/${id}?delete_files=${deleteFiles}`, { method: 'DELETE' }),
    retry: (id: number) =>
      request<DownloadRecord>(`/queue/${id}/retry`, { method: 'POST' }),
    sync: () => request<{ records: DownloadRecord[] }>('/queue/sync', { method: 'POST' }),
  },

  settings: {
    get: () => request<Settings>('/settings'),
    update: (data: Partial<Settings>) =>
      request<Settings>('/settings', { method: 'PUT', body: JSON.stringify(data) }),
    testProwlarr: (data: Partial<Settings>) =>
      request<TestResult>('/settings/test/prowlarr', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    testQbittorrent: (data: Partial<Settings>) =>
      request<TestResult>('/settings/test/qbittorrent', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    prowlarrIndexers: () => request<TestResult>('/settings/prowlarr/indexers'),
  },

  tasks: {
    rssSync: () =>
      request<{ publications: number; grabbed: number }>('/tasks/rss-sync', {
        method: 'POST',
      }),
    autoSearch: () =>
      request<{ publications: number; grabbed: number }>('/tasks/auto-search', {
        method: 'POST',
      }),
  },
};
