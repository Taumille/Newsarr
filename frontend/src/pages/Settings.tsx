import { useEffect, useState } from 'react';
import { api } from '../api';
import type { Settings, TestResult } from '../types';

export default function SettingsPage() {
  const [values, setValues] = useState<Settings | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [test, setTest] = useState<(TestResult & { target: string }) | null>(null);
  const [testing, setTesting] = useState<string | null>(null);

  useEffect(() => {
    api.settings.get().then(setValues).catch((err) => setError(err.message));
  }, []);

  const set = <K extends keyof Settings>(key: K, value: Settings[K]) =>
    setValues((prev) => (prev ? { ...prev, [key]: value } : prev));

  const save = async () => {
    if (!values) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const updated = await api.settings.update(values);
      setValues({ ...updated, ...values, ...updated });
      setNotice('Settings saved.');
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const runTest = async (target: 'prowlarr' | 'qbittorrent') => {
    if (!values) return;
    setTesting(target);
    setTest(null);
    try {
      const result =
        target === 'prowlarr'
          ? await api.settings.testProwlarr(values)
          : await api.settings.testQbittorrent(values);
      setTest({ ...result, target });
    } catch (err) {
      setTest({ ok: false, message: (err as Error).message, target });
    } finally {
      setTesting(null);
    }
  };

  if (!values) {
    return <div className="empty">{error ? error : 'Loading settings…'}</div>;
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <div className="sub">Connect your Prowlarr instance and download client.</div>
        </div>
        <button className="primary" onClick={save} disabled={busy}>
          {busy ? 'Saving…' : 'Save settings'}
        </button>
      </div>

      {error && <div className="alert error">{error}</div>}
      {notice && <div className="alert success">{notice}</div>}
      {test && (
        <div className={`alert ${test.ok ? 'success' : 'error'}`}>
          <strong>
            {test.target === 'prowlarr' ? 'Prowlarr' : 'qBittorrent'} test:{' '}
            {test.ok ? 'passed' : 'failed'}
          </strong>{' '}
          — {test.message}
        </div>
      )}

      <div style={{ maxWidth: 760, display: 'flex', flexDirection: 'column', gap: 20 }}>
        <section className="card">
          <h2 style={{ marginTop: 0, fontSize: 16 }}>Prowlarr</h2>
          <div className="field">
            <label htmlFor="prowlarr_url">Base URL</label>
            <input
              id="prowlarr_url"
              value={values.prowlarr_url}
              onChange={(e) => set('prowlarr_url', e.target.value)}
              placeholder="http://prowlarr:9696"
            />
            <span className="hint">Where Newsarr can reach Prowlarr (may be a remote host).</span>
          </div>
          <div className="field">
            <label htmlFor="prowlarr_api_key">API key</label>
            <input
              id="prowlarr_api_key"
              type="password"
              value={values.prowlarr_api_key}
              onChange={(e) => set('prowlarr_api_key', e.target.value)}
              placeholder={values.prowlarr_api_key_set ? '•••••••• (saved)' : 'Prowlarr → Settings → General'}
            />
            <span className="hint">
              Leave blank to keep the stored key. Found under Prowlarr’s General settings.
            </span>
          </div>
          <button onClick={() => runTest('prowlarr')} disabled={testing === 'prowlarr'}>
            {testing === 'prowlarr' ? 'Testing…' : 'Test connection'}
          </button>
        </section>

        <section className="card">
          <h2 style={{ marginTop: 0, fontSize: 16 }}>qBittorrent</h2>
          <div className="field">
            <label htmlFor="qbit_url">Web UI URL</label>
            <input
              id="qbit_url"
              value={values.qbittorrent_url}
              onChange={(e) => set('qbittorrent_url', e.target.value)}
              placeholder="http://qbittorrent:8080"
            />
          </div>
          <div className="form-row">
            <div className="field">
              <label htmlFor="qbit_user">Username</label>
              <input
                id="qbit_user"
                value={values.qbittorrent_username}
                onChange={(e) => set('qbittorrent_username', e.target.value)}
                placeholder="admin"
              />
            </div>
            <div className="field">
              <label htmlFor="qbit_pass">Password</label>
              <input
                id="qbit_pass"
                type="password"
                value={values.qbittorrent_password}
                onChange={(e) => set('qbittorrent_password', e.target.value)}
                placeholder={values.qbittorrent_password_set ? '•••••••• (saved)' : ''}
              />
            </div>
          </div>
          <div className="form-row">
            <div className="field">
              <label htmlFor="qbit_cat">Category</label>
              <input
                id="qbit_cat"
                value={values.qbittorrent_category}
                onChange={(e) => set('qbittorrent_category', e.target.value)}
                placeholder="newsarr"
              />
              <span className="hint">qBittorrent category used for Newsarr grabs.</span>
            </div>
            <div className="field">
              <label htmlFor="qbit_path">Save path</label>
              <input
                id="qbit_path"
                value={values.qbittorrent_save_path}
                onChange={(e) => set('qbittorrent_save_path', e.target.value)}
                placeholder="qBittorrent default"
              />
            </div>
          </div>
          <button onClick={() => runTest('qbittorrent')} disabled={testing === 'qbittorrent'}>
            {testing === 'qbittorrent' ? 'Testing…' : 'Test connection'}
          </button>
        </section>

        <section className="card">
          <h2 style={{ marginTop: 0, fontSize: 16 }}>Library</h2>
          <div className="field">
            <label htmlFor="library_root">Library root</label>
            <input
              id="library_root"
              value={values.library_root}
              onChange={(e) => set('library_root', e.target.value)}
              placeholder="Defaults to the Newsarr data folder"
            />
            <span className="hint">
              Completed downloads are moved here. Must be reachable by Newsarr.
            </span>
          </div>
          <div className="field">
            <label htmlFor="naming">Naming template</label>
            <input
              id="naming"
              value={values.naming_template}
              onChange={(e) => set('naming_template', e.target.value)}
              placeholder="{title} - {date}"
            />
            <span className="hint">
              Tokens: <code>{'{title}'}</code> and <code>{'{date}'}</code>.
            </span>
          </div>
        </section>

        <div>
          <button className="primary" onClick={save} disabled={busy}>
            {busy ? 'Saving…' : 'Save settings'}
          </button>
        </div>
      </div>
    </>
  );
}
