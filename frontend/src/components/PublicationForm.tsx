import { useState } from 'react';
import type { PublicationInput } from '../types';

export const FORMATS = ['any', 'pdf', 'epub', 'mobi', 'cbz', 'cbr', 'djvu'];

export const FREQUENCIES: { value: PublicationInput['frequency']; label: string }[] = [
  { value: 'irregular', label: 'Irregular / unknown' },
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'biweekly', label: 'Every two weeks' },
  { value: 'monthly', label: 'Monthly' },
  { value: 'quarterly', label: 'Quarterly' },
];

export const WEEKDAYS = [
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
  'Sunday',
];

export const emptyPublication: PublicationInput = {
  title: '',
  monitored: true,
  keywords: '',
  exclude_keywords: '',
  categories: '7010,7020,7030',
  language: '',
  country: '',
  preferred_format: 'any',
  folder: '',
  cover_url: '',
  frequency: 'irregular',
  weekday: null,
  start_date: null,
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

      <div className="field">
        <label htmlFor="exclude_keywords">Exclude keywords</label>
        <input
          id="exclude_keywords"
          value={values.exclude_keywords}
          onChange={(e) => set('exclude_keywords', e.target.value)}
          placeholder="e.g. magazine, sport"
        />
        <span className="hint">
          Comma separated words or phrases. Releases whose title contains one are
          ignored by search, auto-download and automatic tracking.
        </span>
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
          <label htmlFor="frequency">Frequency</label>
          <select
            id="frequency"
            value={values.frequency}
            onChange={(e) => set('frequency', e.target.value as PublicationInput['frequency'])}
          >
            {FREQUENCIES.map((frequency) => (
              <option key={frequency.value} value={frequency.value}>
                {frequency.label}
              </option>
            ))}
          </select>
          <span className="hint">Used to generate the expected issue calendar.</span>
        </div>
        <div className="field">
          <label htmlFor="start_date">Calendar start date</label>
          <input
            id="start_date"
            type="date"
            value={values.start_date ?? ''}
            onChange={(e) => set('start_date', e.target.value || null)}
          />
          <span className="hint">e.g. 2020-01-01 — all issues since then are tracked.</span>
        </div>
      </div>

      {(values.frequency === 'weekly' || values.frequency === 'biweekly') && (
        <div className="field">
          <label htmlFor="weekday">Publication day</label>
          <select
            id="weekday"
            value={values.weekday ?? ''}
            onChange={(e) => set('weekday', e.target.value === '' ? null : Number(e.target.value))}
          >
            <option value="">Use the start date's weekday</option>
            {WEEKDAYS.map((day, index) => (
              <option key={day} value={index}>
                {day}
              </option>
            ))}
          </select>
          <span className="hint">For example: weekly on Wednesday.</span>
        </div>
      )}

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
        <label htmlFor="cover_url">Cover image URL (optional)</label>
        <input
          id="cover_url"
          value={values.cover_url}
          onChange={(e) => set('cover_url', e.target.value)}
          placeholder="https://…/cover.jpg"
        />
        <span className="hint">
          You can also upload an image from the publication page.
        </span>
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
