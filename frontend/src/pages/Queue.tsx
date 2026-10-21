import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import type { DownloadRecord } from '../types';
import { formatBytes, formatDateTime } from '../format';

const ACTIVE: DownloadRecord['status'][] = ['queued', 'downloading', 'completed'];

export default function Queue() {
  const [records, setRecords] = useState<DownloadRecord[] | null>(null);
  const [error, setError] = useState('');
  const [syncAt, setSyncAt] = useState<string>('');

  const load = useCallback(() => {
    api.queue
      .list()
      .then((data) => {
        setRecords(data.records);
        setSyncAt(new Date().toLocaleTimeString());
      })
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, 10000);
    return () => clearInterval(timer);
  }, [load]);

  const sync = async () => {
    try {
      const data = await api.queue.sync();
      setRecords(data.records);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const remove = async (record: DownloadRecord) => {
    const deleteFiles = record.status === 'imported' || record.status === 'failed'
      ? false
      : window.confirm('Also delete the files from the download client?');
    try {
      await api.queue.remove(record.id, deleteFiles);
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const retry = async (record: DownloadRecord) => {
    try {
      await api.queue.retry(record.id);
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const active = records?.filter((r) => ACTIVE.includes(r.status)).length ?? 0;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Queue</h1>
          <div className="sub">
            {records ? `${active} active · ${records.length} total` : 'Loading…'}
            {syncAt && ` · refreshed ${syncAt}`}
          </div>
        </div>
        <button onClick={sync}>↻ Refresh now</button>
      </div>

      {error && <div className="alert error">{error}</div>}

      {records && records.length === 0 && (
        <div className="empty">Nothing here yet. Grab a release from a publication to get started.</div>
      )}

      {records && records.length > 0 && (
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <table>
            <thead>
              <tr>
                <th>Release</th>
                <th>Status</th>
                <th>Progress</th>
                <th>Size</th>
                <th>Added</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {records.map((record) => (
                <tr key={record.id}>
                  <td>
                    <div>{record.title}</div>
                    <div className="mono">
                      {record.indexer}
                      {record.publication_id && (
                        <>
                          {' · '}
                          <Link to={`/publications/${record.publication_id}`}>publication</Link>
                        </>
                      )}
                    </div>
                    {record.status === 'imported' && record.imported_path && (
                      <div className="mono">→ {record.imported_path}</div>
                    )}
                    {record.error_message && (
                      <div className="mono" style={{ color: 'var(--danger)' }}>
                        {record.error_message}
                      </div>
                    )}
                  </td>
                  <td>
                    <span className={`status ${record.status}`}>{record.status}</span>
                  </td>
                  <td>
                    <div className="progress">
                      <span style={{ width: `${record.progress}%` }} />
                    </div>
                    <div className="mono">{record.progress}%</div>
                  </td>
                  <td>{formatBytes(record.size)}</td>
                  <td>{formatDateTime(record.added_at)}</td>
                  <td className="actions">
                    {record.status === 'failed' && (
                      <button className="small" onClick={() => retry(record)}>
                        Retry
                      </button>
                    )}{' '}
                    <button className="small danger" onClick={() => remove(record)}>
                      Remove
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
