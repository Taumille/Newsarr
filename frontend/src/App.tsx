import { useEffect, useState } from 'react';
import { NavLink, Route, Routes } from 'react-router-dom';
import { api } from './api';
import type { SystemStatus } from './types';
import Publications from './pages/Publications';
import PublicationDetail from './pages/PublicationDetail';
import AddPublication from './pages/AddPublication';
import Queue from './pages/Queue';
import SettingsPage from './pages/Settings';

const navItems = [
  { to: '/', label: 'Library', icon: '📰', end: true },
  { to: '/add', label: 'Add publication', icon: '＋' },
  { to: '/queue', label: 'Queue', icon: '⬇' },
  { to: '/settings', label: 'Settings', icon: '⚙' },
];

export default function App() {
  const [status, setStatus] = useState<SystemStatus | null>(null);

  useEffect(() => {
    api.system.status().then(setStatus).catch(() => setStatus(null));
    const timer = setInterval(() => {
      api.system.status().then(setStatus).catch(() => undefined);
    }, 15000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          News<span>arr</span>
        </div>
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) => `navlink${isActive ? ' active' : ''}`}
          >
            <span aria-hidden>{item.icon}</span>
            {item.label}
            {item.to === '/queue' && status && status.active_downloads > 0 && (
              <span className="badge monitored" style={{ marginLeft: 'auto' }}>
                {status.active_downloads}
              </span>
            )}
          </NavLink>
        ))}
        <div className="sidebar-footer">
          <div>v{status?.version ?? '…'}</div>
          <div>
            {status?.prowlarr_configured ? '✅ Prowlarr' : '⚠️ Prowlarr not set'}
          </div>
          <div>
            {status?.download_client_configured ? '✅ qBittorrent' : '⚠️ qBittorrent not set'}
          </div>
        </div>
      </aside>

      <main className="main">
        <Routes>
          <Route path="/" element={<Publications />} />
          <Route path="/add" element={<AddPublication />} />
          <Route path="/publications/:id" element={<PublicationDetail />} />
          <Route path="/queue" element={<Queue />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route
            path="*"
            element={<div className="empty">Page not found.</div>}
          />
        </Routes>
      </main>
    </div>
  );
}
