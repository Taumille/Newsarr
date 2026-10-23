export type TrackedStatus =
  | 'queued'
  | 'downloading'
  | 'completed'
  | 'imported'
  | 'failed';

export type Protocol = 'torrent' | 'usenet';

export type Frequency =
  | 'irregular'
  | 'daily'
  | 'weekly'
  | 'biweekly'
  | 'monthly'
  | 'quarterly';

export interface Publication {
  id: number;
  title: string;
  slug: string;
  monitored: boolean;
  keywords: string;
  exclude_keywords: string;
  categories: string;
  language: string;
  country: string;
  preferred_format: string;
  folder: string;
  cover_url: string;
  frequency: Frequency;
  weekday: number | null;
  start_date: string | null;
  has_cover: boolean;
  issue_total: number;
  issue_owned: number;
  issue_missing: number;
  issue_upcoming: number;
  created_at: string;
  updated_at: string;
  last_search_at: string | null;
}

export interface PublicationInput {
  title: string;
  monitored: boolean;
  keywords: string;
  exclude_keywords: string;
  categories: string;
  language: string;
  country: string;
  preferred_format: string;
  folder: string;
  cover_url: string;
  frequency: Frequency;
  weekday: number | null;
  start_date: string | null;
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

export type IssueStatus = 'expected' | 'grabbed' | 'owned' | 'ignored';

export interface Issue {
  id: number;
  publication_id: number;
  issue_date: string;
  label: string;
  status: IssueStatus;
  download_id: number | null;
  file_path: string;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface IssueSummary {
  total: number;
  owned: number;
  missing: number;
  upcoming: number;
  grabbed: number;
  ignored: number;
}

export interface IssueList {
  issues: Issue[];
  summary: IssueSummary;
  total: number;
  offset: number;
  limit: number;
}

export type IssueFilter =
  | 'all'
  | 'missing'
  | 'owned'
  | 'grabbed'
  | 'upcoming'
  | 'ignored';

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
  rss_sync_enabled: boolean;
  rss_sync_interval_minutes: number;
  rss_recent_hours: number;
  auto_search_enabled: boolean;
  auto_search_interval_minutes: number;
  auto_search_recent_days: number;
  auto_search_max_grabs: number;
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
