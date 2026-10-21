import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import type { PublicationInput } from '../types';
import PublicationForm, { emptyPublication } from '../components/PublicationForm';

export default function AddPublication() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const submit = async (values: PublicationInput) => {
    setBusy(true);
    setError('');
    try {
      const created = await api.publications.create(values);
      navigate(`/publications/${created.id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Add publication</h1>
          <div className="sub">Track a newspaper or magazine and search Prowlarr for its issues.</div>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}

      <div style={{ maxWidth: 720 }}>
        <PublicationForm
          initial={emptyPublication}
          submitLabel="Add publication"
          busy={busy}
          onSubmit={submit}
          onCancel={() => navigate('/')}
        />
      </div>
    </>
  );
}
