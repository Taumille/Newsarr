import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import type {
  Issue,
  IssueFilter,
  IssueSummary,
  Release,
} from '../types';
import { formatBytes } from '../format';

const LIMIT = 500;

const FILTERS: { value: IssueFilter; label: string }[] = [
  { value: 'all', label: 'All issues' },
  { value: 'missing', label: 'Missing' },
  { value: 'owned', label: 'Owned' },
  { value: 'grabbed', label: 'Grabbed' },
  { value: 'upcoming', label: 'Upcoming' },
  { value: 'ignored', label: 'Ignored' },
];

function todayIso(): string {
  return new Date().toLocaleDateString('en-CA');
}

function displayStatus(issue: Issue): { key: string; label: string } {
  if (issue.status === 'expected') {
    return issue.issue_date <= todayIso()
      ? { key: 'missing', label: 'Missing' }
      : { key: 'upcoming', label: 'Upcoming' };
  }
  return { key: issue.status, label: issue.status };
}

function formatIssueDate(value: string): string {
  const date = new Date(`${value}T12:00:00Z`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, {
    weekday: 'short',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  });
}

interface Props {
  publicationId: number;
  refreshKey?: number;
  onChanged: () => void;
}

export default function IssueLibrary({ publicationId, refreshKey = 0, onChanged }: Props) {
  const [issues, setIssues] = useState<Issue[]>([]);
  const [summary, setSummary] = useState<IssueSummary | null>(null);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState<IssueFilter>('all');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [actionBusy, setActionBusy] = useState('');

  const [selected, setSelected] = useState<Issue | null>(null);
  const [releases, setReleases] = useState<Release[] | null>(null);
  const [searchBusy, setSearchBusy] = useState(false);
  const [grabbing, setGrabbing] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.issues.list(publicationId, filter, LIMIT);
      setIssues(data.issues);
      setSummary(data.summary);
      setTotal(data.total);
      setError('');
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [publicationId, filter, refreshKey]);

  useEffect(() => {
    load();
  }, [load]);

  const refresh = () => {
    load();
    onChanged();
  };

  const generate = async () => {
    setActionBusy('generate');
    setError('');
    setNotice('');
    try {
      const result = await api.issues.generate(publicationId);
      setNotice(
        `Calendar updated: ${result.added} added, ${result.removed} removed, ${result.total} scheduled.`,
      );
      refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setActionBusy('');
    }
  };

  const scan = async () => {
    setActionBusy('scan');
    setError('');
    setNotice('');
    try {
      const result = await api.issues.scan(publicationId);
      setNotice(
        `Scanned ${result.scanned} file(s): ${result.matched} issue file(s) matched, ${result.owned} owned in total.`,
      );
      refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setActionBusy('');
    }
  };

  const searchMissing = async () => {
    setActionBusy('missing');
    setError('');
    setNotice('');
    try {
      const result = await api.issues.searchMissing(publicationId, 10);
      setNotice(
        result.missing === 0
          ? 'No missing issues to search for.'
          : `Checked ${result.searched} missing issue(s); grabbed ${result.grabbed}.`,
      );
      refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setActionBusy('');
    }
  };

  const mark = async (issue: Issue, status: Issue['status']) => {
    setActionBusy(`mark-${issue.id}`);
    setError('');
    setNotice('');
    try {
      await api.issues.update(issue.id, { status });
      if (selected?.id === issue.id) setSelected({ ...issue, status });
      refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setActionBusy('');
    }
  };

  const searchIssue = async (issue: Issue) => {
    setSelected(issue);
    setReleases(null);
    setSearchBusy(true);
    setError('');
    setNotice('');
    try {
      const response = await api.issues.search(issue.id);
      setReleases(response.releases);
      if (response.releases.length === 0) {
        setNotice(`No dated release found for ${formatIssueDate(issue.issue_date)}.`);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSearchBusy(false);
    }
  };

  const autoGrab = async (issue: Issue) => {
    setActionBusy(`auto-${issue.id}`);
    setError('');
    setNotice('');
    try {
      const record = await api.issues.autoGrab(issue.id);
      setNotice(`Auto-grabbed: ${record.title}`);
      setSelected(null);
      setReleases(null);
      refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setActionBusy('');
    }
  };

  const grab = async (release: Release) => {
    if (!selected) return;
    setGrabbing(release.guid || release.title);
    setError('');
    setNotice('');
    try {
      await api.issues.grab(selected.id, release, publicationId);
      setNotice(`Grabbed: ${release.title}`);
      setReleases([]);
      refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setGrabbing(null);
    }
  };

  const stats = summary;
  const shown = issues.length;

  return (
    <div className="card issue-panel">
      <div className="issue-head">
        <div>
          <h2>Issues</h2>
          <div className="sub">
            {stats
              ? `${stats.total} in catalog · ${stats.owned} owned · ${stats.missing} missing · ${stats.upcoming} upcoming`
              : 'Loading…'}
          </div>
        </div>
        <div className="issue-actions">
          <button className="small" onClick={generate} disabled={!!actionBusy}>
            {actionBusy === 'generate' ? 'Generating…' : 'Generate calendar'}
          </button>
          <button className="small" onClick={scan} disabled={!!actionBusy}>
            {actionBusy === 'scan' ? 'Scanning…' : 'Scan library'}
          </button>
          <button className="small primary" onClick={searchMissing} disabled={!!actionBusy}>
            {actionBusy === 'missing' ? 'Searching…' : '⤓ Search all missing'}
          </button>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}
      {notice && <div className="alert info">{notice}</div>}

      <div className="issue-filter">
        <label htmlFor="issue-filter">Show</label>
        <select
          id="issue-filter"
          value={filter}
          onChange={(e) => setFilter(e.target.value as IssueFilter)}
        >
          {FILTERS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <span className="sub">
          {loading ? 'Loading…' : `Showing ${shown} of ${total}`}
          {total > LIMIT && ` (latest ${LIMIT}; narrow the filter to see older issues)`}
        </span>
      </div>

      {!loading && issues.length === 0 && (
        <div className="empty" style={{ padding: 30 }}>
          {total === 0
            ? 'No issues in the catalog yet. Set a frequency and start date, then click “Generate calendar”.'
            : 'No issues match this filter.'}
        </div>
      )}

      {issues.length > 0 && (
        <div className="issue-table-wrap">
          <table>
            <thead>
              <tr>
                <th>Issue date</th>
                <th>Status</th>
                <th>File / label</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {issues.map((issue) => {
                const state = displayStatus(issue);
                return (
                  <tr key={issue.id} className={selected?.id === issue.id ? 'selected-row' : ''}>
                    <td>{formatIssueDate(issue.issue_date)}</td>
                    <td>
                      <span className={`issue-status ${state.key}`}>{state.label}</span>
                    </td>
                    <td>
                      {issue.label && <div>{issue.label}</div>}
                      {issue.file_path ? (
                        <div className="mono issue-path" title={issue.file_path}>
                          {issue.file_path}
                        </div>
                      ) : (
                        <span className="mono">—</span>
                      )}
                    </td>
                    <td className="actions">
                      <button
                        className="small"
                        onClick={() => searchIssue(issue)}
                        disabled={searchBusy || issue.status === 'owned'}
                      >
                        {searchBusy && selected?.id === issue.id ? 'Searching…' : 'Search'}
                      </button>{' '}
                      <button
                        className="small primary"
                        title="Search Prowlarr and grab the release with the most seeders"
                        onClick={() => autoGrab(issue)}
                        disabled={
                          !!actionBusy || searchBusy || issue.status !== 'expected'
                        }
                      >
                        {actionBusy === `auto-${issue.id}`
                          ? 'Auto-downloading…'
                          : 'Auto-download'}
                      </button>{' '}
                      {issue.status === 'owned' ? (
                        <button
                          className="small"
                          onClick={() => mark(issue, 'expected')}
                          disabled={actionBusy === `mark-${issue.id}`}
                        >
                          Mark missing
                        </button>
                      ) : (
                        <button
                          className="small"
                          onClick={() => mark(issue, 'owned')}
                          disabled={actionBusy === `mark-${issue.id}`}
                        >
                          Mark owned
                        </button>
                      )}{' '}
                      <button
                        className="small ghost"
                        onClick={() => mark(issue, issue.status === 'ignored' ? 'expected' : 'ignored')}
                        disabled={actionBusy === `mark-${issue.id}`}
                      >
                        {issue.status === 'ignored' ? 'Unignore' : 'Ignore'}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <div className="issue-search">
          <div className="issue-head">
            <div>
              <h2>Releases for {formatIssueDate(selected.issue_date)}</h2>
              <div className="sub">Only releases whose date matches this issue are shown.</div>
            </div>
            <button className="small ghost" onClick={() => { setSelected(null); setReleases(null); }}>
              Close
            </button>
          </div>

          {searchBusy && <div className="sub">Searching Prowlarr…</div>}

          {!searchBusy && releases && releases.length === 0 && (
            <div className="empty" style={{ padding: 24 }}>
              No release found for this date. Try the general search below, or grab it manually.
            </div>
          )}

          {!searchBusy && releases && releases.length > 0 && (
            <div className="issue-table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Release</th>
                    <th>Indexer</th>
                    <th>Size</th>
                    <th>Seeds</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {releases.map((release) => (
                    <tr key={`${release.guid}-${release.indexer_id}-${release.title}`}>
                      <td>
                        {release.info_url ? (
                          <a href={release.info_url} target="_blank" rel="noreferrer">
                            {release.title}
                          </a>
                        ) : (
                          release.title
                        )}
                      </td>
                      <td>{release.indexer}</td>
                      <td>{formatBytes(release.size)}</td>
                      <td>{release.seeders ?? '—'}</td>
                      <td className="actions">
                        <button
                          className="small primary"
                          onClick={() => grab(release)}
                          disabled={grabbing === (release.guid || release.title)}
                        >
                          {grabbing === (release.guid || release.title) ? 'Grabbing…' : 'Grab'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
