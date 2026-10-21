import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api';
import type { Publication } from '../types';
import { relativeTime } from '../format';

export default function Publications() {
  const [items, setItems] = useState<Publication[] | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [running, setRunning] = useState(false);
  const navigate = useNavigate();

  const load = useCallback(() => {
    api.publications
      .list()
      .then((data) => {
        setItems(data);
        setError('');
      })
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const toggleMonitored = async (publication: Publication) => {
    try {
      await api.publications.update(publication.id, { monitored: !publication.monitored });
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const remove = async (publication: Publication) => {
    if (!window.confirm(`Remove "${publication.title}"? Existing downloaded files are kept.`)) {
      return;
    }
    try {
      await api.publications.remove(publication.id);
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const autoSearchAll = async () => {
    setRunning(true);
    setError('');
    setNotice('');
    try {
      const result = await api.tasks.autoSearch();
      setNotice(
        `Searched ${result.publications} publication(s) — grabbed ${result.grabbed} new issue(s).`,
      );
      load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRunning(false);
    }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Library</h1>
          <div className="sub">
            {items ? `${items.length} publication${items.length === 1 ? '' : 's'} tracked` : 'Loading…'}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={autoSearchAll} disabled={running}>
            {running ? 'Searching…' : '⤓ Auto-search all'}
          </button>
          <button className="primary" onClick={() => navigate('/add')}>
            ＋ Add publication
          </button>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}
      {notice && <div className="alert info">{notice}</div>}

      {items && items.length === 0 && (
        <div className="empty">
          <p>No publications tracked yet.</p>
          <button className="primary" onClick={() => navigate('/add')}>
            Add your first newspaper
          </button>
        </div>
      )}

      <div className="grid">
        {items?.map((publication) => (
          <div className="pub-card" key={publication.id}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <Link to={`/publications/${publication.id}`}>
                <h3>{publication.title}</h3>
              </Link>
              <span className={`badge ${publication.monitored ? 'monitored' : 'unmonitored'}`}>
                {publication.monitored ? 'Monitored' : 'Paused'}
              </span>
            </div>

            <div className="meta">
              {publication.preferred_format !== 'any' && (
                <span className="badge">{publication.preferred_format}</span>
              )}
              {publication.language && <span className="badge">{publication.language}</span>}
              {publication.country && <span className="badge">{publication.country}</span>}
              {publication.categories.split(',').filter(Boolean).map((cat) => (
                <span className="badge" key={cat}>
                  {cat.trim()}
                </span>
              ))}
            </div>

            <div className="meta">
              <span>Last search: {relativeTime(publication.last_search_at)}</span>
            </div>

            <div className="actions">
              <Link to={`/publications/${publication.id}`}>
                <button className="small">Open</button>
              </Link>
              <button className="small" onClick={() => toggleMonitored(publication)}>
                {publication.monitored ? 'Pause' : 'Resume'}
              </button>
              <button className="small danger" onClick={() => remove(publication)}>
                Remove
              </button>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
