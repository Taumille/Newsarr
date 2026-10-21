import { useState } from 'react';
import type { PublicationInput } from '../types';

export const FORMATS = ['any', 'pdf', 'epub', 'mobi', 'cbz', 'cbr', 'djvu'];

export const emptyPublication: PublicationInput = {
  title: '',
  monitored: true,
  keywords: '',
  categories: '7010,7020,7030',
  language: '',
  country: '',
  preferred_format: 'any',
  folder: '',
  cover_url: '',
};

interface Props {
  initial: PublicationInput;
  submitLabel: string;
  busy?: boolean;
  onSubmit: (values: PublicationInput) => void;
  onCancel?: () => void;
}

export default function PublicationForm({
  initial,
  submitLabel,
  busy,
  onSubmit,
  onCancel,
}: Props) {
  const [values, setValues] = useState<PublicationInput>(initial);

  const set = <K extends keyof PublicationInput>(key: K, value: PublicationInput[K]) =>
    setValues((prev) => ({ ...prev, [key]: value }));

  return (
    <form
      className="card"
      onSubmit={(event) => {
        event.preventDefault();
        if (!values.title.trim()) return;
        onSubmit({ ...values, title: values.title.trim() });
      }}
    >
      <div className="field">
        <label htmlFor="title">Title *</label>
        <input
          id="title"
          value={values.title}
          onChange={(e) => set('title', e.target.value)}
          placeholder="e.g. The Guardian"
          autoFocus
          required
        />
        <span className="hint">The newspaper or magazine name, as it appears on releases.</span>
      </div>

      <div className="form-row">
        <div className="field">
          <label htmlFor="keywords">Search keywords</label>
          <input
            id="keywords"
            value={values.keywords}
            onChange={(e) => set('keywords', e.target.value)}
            placeholder="e.g. pdf"
          />
          <span className="hint">Extra words appended to the title during search.</span>
        </div>
        <div className="field">
          <label htmlFor="categories">Newznab categories</label>
          <input
            id="categories"
            value={values.categories}
            onChange={(e) => set('categories', e.target.value)}
            placeholder="7010,7020"
          />
          <span className="hint">Comma separated category ids (7010 = Books/Mags).</span>
        </div>
      </div>

      <div className="form-row">
        <div className="field">
          <label htmlFor="language">Language</label>
          <input
            id="language"
            value={values.language}
            onChange={(e) => set('language', e.target.value)}
            placeholder="en"
          />
        </div>
        <div className="field">
          <label htmlFor="country">Country</label>
          <input
            id="country"
            value={values.country}
            onChange={(e) => set('country', e.target.value)}
            placeholder="gb"
          />
        </div>
      </div>

      <div className="form-row">
        <div className="field">
          <label htmlFor="format">Preferred format</label>
          <select
            id="format"
            value={values.preferred_format}
            onChange={(e) => set('preferred_format', e.target.value)}
          >
            {FORMATS.map((format) => (
              <option key={format} value={format}>
                {format}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="folder">Library subfolder</label>
          <input
            id="folder"
            value={values.folder}
            onChange={(e) => set('folder', e.target.value)}
            placeholder="Defaults to the title"
          />
        </div>
      </div>

      <div className="field">
        <label>
          <input
            type="checkbox"
            checked={values.monitored}
            onChange={(e) => set('monitored', e.target.checked)}
            style={{ width: 'auto', marginRight: 8 }}
          />
          Monitored
        </label>
        <span className="hint">Unmonitored publications are skipped by automatic searches.</span>
      </div>

      <div className="form-actions">
        <button className="primary" type="submit" disabled={busy}>
          {busy ? 'Saving…' : submitLabel}
        </button>
        {onCancel && (
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}
