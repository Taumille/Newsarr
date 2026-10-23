import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api } from '../api';
import type { Publication, PublicationInput, Release } from '../types';
import { formatBytes, formatDate } from '../format';
import PublicationForm from '../components/PublicationForm';
import CoverPanel from '../components/CoverPanel';
import IssueLibrary from '../components/IssueLibrary';

export default function PublicationDetail() {
  const { id } = useParams();
  const publicationId = Number(id);
  const navigate = useNavigate();

  const [publication, setPublication] = useState<Publication | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [searching, setSearching] = useState(false);
  const [releases, setReleases] = useState<Release[] | null>(null);
  const [extra, setExtra] = useState('');
  const [grabbing, setGrabbing] = useState<string | null>(null);
  const [autoBusy, setAutoBusy] = useState(false);
  const [issueVersion, setIssueVersion] = useState(0);

  const load = useCallback(() => {
    api.publications
      .get(publicationId)
      .then(setPublication)
      .catch((err) => setError(err.message));
  }, [publicationId]);

  useEffect(() => {
    load();
  }, [load]);

  const save = async (values: PublicationInput) => {
    setBusy(true);
    setNotice('');
    try {
      await api.publications.update(publicationId, values);
      load();
      // Frequency / start date changes rebuild the calendar server-side.
      setIssueVersion((value) => value + 1);
      setNotice('Saved.');
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const search = async () => {
    setSearching(true);
    setError('');
    setNotice('');
    try {
      const response = await api.publications.search(publicationId, extra);
      setReleases(response.releases);
      load();
      if (response.releases.length === 0) {
        setNotice('No releases found. Try adjusting keywords or categories.');
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSearching(false);
    }
  };

  const grab = async (release: Release) => {
    setGrabbing(release.guid || release.title);
    setError('');
    setNotice('');
    try {
      await api.queue.grab(release, publicationId);
      setNotice(`Grabbed: ${release.title}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setGrabbing(null);
    }
  };

  const autoSearch = async () => {
    setAutoBusy(true);
    setError('');
    setNotice('');
    try {
      const grabbed = await api.publications.autoSearch(publicationId);
      setNotice(
        grabbed.length
          ? `Auto-grabbed ${grabbed.length} new issue(s).`
          : 'No new issues found.',
      );
      load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setAutoBusy(false);
    }
  };

  if (!publication) {
    return (
      <div className="empty">
        {error ? <span style={{ color: 'var(--danger)' }}>{error}</span> : 'Loading…'}
      </div>
    );
  }

  const initial: PublicationInput = {
    title: publication.title,
    monitored: publication.monitored,
    keywords: publication.keywords,
    categories: publication.categories,
    language: publication.language,
    country: publication.country,
    preferred_format: publication.preferred_format,
    folder: publication.folder,
    cover_url: publication.cover_url,
    frequency: publication.frequency,
    weekday: publication.weekday,
    start_date: publication.start_date,
  };

  return (
    <>
      <div className="page-head">
        <div>
          <div className="sub">
            <Link to="/">← Library</Link>
          </div>
          <h1>{publication.title}</h1>
          <div className="sub">
            {publication.frequency === 'irregular'
              ? 'Irregular schedule'
              : `${publication.frequency}${publication.weekday !== null ? ` · ${['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][publication.weekday]}` : ''}`}
            {publication.start_date ? ` · since ${publication.start_date}` : ''}
          </div>
          <div className="sub">
            {publication.issue_owned} owned · {publication.issue_missing} missing ·{' '}
            {publication.issue_upcoming} upcoming
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="primary" onClick={search} disabled={searching}>
            {searching ? 'Searching…' : '🔍 Search for releases'}
          </button>
          <button onClick={autoSearch} disabled={autoBusy}>
            {autoBusy ? 'Searching…' : '⤓ Auto-search'}
          </button>
          <button onClick={() => navigate('/queue')}>View queue</button>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}
      {notice && <div className="alert success">{notice}</div>}

      <div className="detail-top">
        <CoverPanel publication={publication} onChanged={load} />
        <div className="detail-settings">
          <h2 style={{ fontSize: 16 }}>Settings</h2>
          <PublicationForm
            key={publication.id}
            initial={initial}
            submitLabel="Save changes"
            busy={busy}
            onSubmit={save}
          />
        </div>
      </div>

      <IssueLibrary
        publicationId={publication.id}
        refreshKey={issueVersion}
        onChanged={load}
      />

      <div className="card" style={{ margin: '20px 0 16px' }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end' }}>
          <div className="field" style={{ flex: 1, marginBottom: 0 }}>
            <label htmlFor="extra">Extra search terms (optional)</label>
            <input
              id="extra"
              value={extra}
              onChange={(e) => setExtra(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && search()}
              placeholder="e.g. 2026 or weekend"
            />
          </div>
          <button className="primary" onClick={search} disabled={searching}>
            Search
          </button>
        </div>
      </div>

      {releases && releases.length > 0 && (
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <table>
            <thead>
              <tr>
                <th>Release</th>
                <th>Indexer</th>
                <th>Size</th>
                <th>Published</th>
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
                    <div className="mono">
                      {release.categories.map((category) => category.name).filter(Boolean).join(' · ')}
                    </div>
                  </td>
                  <td>{release.indexer}</td>
                  <td>{formatBytes(release.size)}</td>
                  <td>{formatDate(release.publish_date)}</td>
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
    </>
  );
}
