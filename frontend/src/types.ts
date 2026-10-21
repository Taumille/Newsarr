export type TrackedStatus =
  | 'queued'
  | 'downloading'
  | 'completed'
  | 'imported'
  | 'failed';

export type Protocol = 'torrent' | 'usenet';

export interface Publication {
  id: number;
  title: string;
  slug: string;
  monitored: boolean;
  keywords: string;
  categories: string;
  language: string;
  country: string;
  preferred_format: string;
  folder: string;
  cover_url: string;
  created_at: string;
  updated_at: string;
  last_search_at: string | null;
}

export interface PublicationInput {
  title: string;
  monitored: boolean;
  keywords: string;
  categories: string;
  language: string;
  country: string;
  preferred_format: string;
  folder: string;
  cover_url: string;
}

export interface ReleaseCategory {
  id: number | null;
  name: string;
}

export interface Release {
  guid: string;
  title: string;
  indexer: string;
  indexer_id: number | null;
  size: number;
  download_url: string;
  magnet_url: string;
  info_url: string;
  publish_date: string | null;
  protocol: Protocol;
  categories: ReleaseCategory[];
  seeders: number | null;
}

export interface SearchResponse {
  query: string;
  releases: Release[];
}

export interface DownloadRecord {
  id: number;
  publication_id: number | null;
  title: string;
  guid: string;
  indexer: string;
  indexer_id: number | null;
  protocol: Protocol;
  size: number;
  client: string;
  client_hash: string;
  save_path: string;
  content_path: string;
  status: TrackedStatus;
  progress: number;
  error_message: string;
  imported_path: string;
  added_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface Settings {
  prowlarr_url: string;
  prowlarr_api_key: string;
  qbittorrent_url: string;
  qbittorrent_username: string;
  qbittorrent_password: string;
  qbittorrent_category: string;
  qbittorrent_save_path: string;
  library_root: string;
  naming_template: string;
  prowlarr_api_key_set: boolean;
  qbittorrent_password_set: boolean;
}

export interface SystemStatus {
  version: string;
  publication_count: number;
  active_downloads: number;
  prowlarr_configured: boolean;
  download_client_configured: boolean;
  library_root: string;
}

export interface TestResult {
  ok: boolean;
  message: string;
  details?: Record<string, unknown> | null;
}
