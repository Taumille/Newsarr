import { useRef, useState } from 'react';
import { api } from '../api';
import type { Publication } from '../types';

interface Props {
  publication: Publication;
  onChanged: () => void;
}

export default function CoverPanel({ publication, onChanged }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const src = publication.has_cover
    ? `/api/v1/publications/${publication.id}/cover?v=${encodeURIComponent(publication.updated_at)}`
    : publication.cover_url;

  const upload = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setError('');
    try {
      await api.publications.uploadCover(publication.id, file);
      onChanged();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  const remove = async () => {
    if (!window.confirm('Remove the uploaded cover image?')) return;
    setBusy(true);
    setError('');
    try {
      await api.publications.removeCover(publication.id);
      onChanged();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="cover-panel">
      <div className="cover-frame">
        {src ? (
          <img className="cover-image" src={src} alt={`${publication.title} cover`} />
        ) : (
          <div className="cover-placeholder">{publication.title.slice(0, 2).toUpperCase()}</div>
        )}
      </div>
      <div className="cover-actions">
        <input
          ref={inputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp,image/gif"
          style={{ display: 'none' }}
          onChange={(e) => upload(e.target.files?.[0])}
        />
        <button className="small" disabled={busy} onClick={() => inputRef.current?.click()}>
          {busy ? 'Uploading…' : publication.has_cover ? 'Replace image' : 'Upload image'}
        </button>
        {publication.has_cover && (
          <button className="small danger" disabled={busy} onClick={remove}>
            Remove
          </button>
        )}
        {error && <div className="cover-error">{error}</div>}
      </div>
    </div>
  );
}
