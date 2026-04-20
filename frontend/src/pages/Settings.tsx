import { useEffect, useState } from "react";
import { getSettings, updateSettings } from "../api";
import type { AppSettings, AppSettingsResponse } from "../types";

const STAGE_FIELDS: { key: keyof AppSettings; label: string }[] = [
  { key: "model_task_spec", label: "Task spec parsing" },
  { key: "model_source_card", label: "Source card generation" },
  { key: "model_topic_ideation", label: "Topic ideation" },
  { key: "model_research", label: "Research" },
  { key: "model_drafting", label: "Drafting" },
  { key: "model_drafting_revision", label: "Draft revision" },
  { key: "model_validation", label: "Validation" },
];

const EMPTY: AppSettings = {
  llm_model: "",
  model_task_spec: "",
  model_source_card: "",
  model_topic_ideation: "",
  model_research: "",
  model_drafting: "",
  model_drafting_revision: "",
  model_validation: "",
  ocr_tier: "small",
  chunk_target_chars: 3000,
  chunk_overlap_chars: 300,
  max_full_read_pages: 30,
  min_text_chars_per_page: 300,
};

export default function Settings() {
  const [info, setInfo] = useState<Pick<AppSettingsResponse, "llm_provider" | "api_key_configured"> | null>(null);
  const [form, setForm] = useState<AppSettings>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSettings()
      .then((data) => {
        const { llm_provider, api_key_configured, ...settings } = data;
        setInfo({ llm_provider, api_key_configured });
        setForm(settings);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load settings."))
      .finally(() => setLoading(false));
  }, []);

  function setStr(key: keyof AppSettings, value: string) {
    setForm((prev) => ({ ...prev, [key]: value }));
    setSaved(false);
  }

  function setNum(key: keyof AppSettings, value: string) {
    const n = parseInt(value, 10);
    if (!Number.isNaN(n) && n > 0) {
      setForm((prev) => ({ ...prev, [key]: n }));
      setSaved(false);
    }
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const data = await updateSettings(form);
      const { llm_provider, api_key_configured, ...settings } = data;
      setInfo({ llm_provider, api_key_configured });
      setForm(settings);
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save settings.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="page">
        <div className="loading-state"><div className="spinner-large" /></div>
      </div>
    );
  }

  return (
    <div className="page">
      <header className="page-header">
        <p className="eyebrow">Configuration</p>
        <h1>Settings</h1>
        <p className="subtitle">Changes take effect on the next upload or pipeline run. API keys and provider are set via environment variables.</p>
      </header>

      {info && (
        <div className="settings-env-info">
          <span className="settings-env-row">
            <span className="settings-env-label">Provider</span>
            <code className="settings-env-value">{info.llm_provider}</code>
          </span>
          <span className="settings-env-row">
            <span className="settings-env-label">API key</span>
            <span className={`settings-env-value ${info.api_key_configured ? "settings-ok" : "settings-warn"}`}>
              {info.api_key_configured ? "Configured" : "Not set — set the env var before running"}
            </span>
          </span>
        </div>
      )}

      <section className="section">
        <h2>Default model</h2>
        <p className="subtitle">Used for all stages unless a per-stage override is set. Leave blank to use the adapter default.</p>
        <input
          className="instruction-input"
          placeholder="e.g. claude-opus-4-7"
          value={form.llm_model}
          onChange={(e) => setStr("llm_model", e.target.value)}
        />
      </section>

      <section className="section">
        <h2>Source ingestion</h2>
        <p className="subtitle">Applied when uploading new source files. Existing sources are not re-processed.</p>
        <div className="settings-stage-grid">
          <div className="settings-stage-row">
            <label className="settings-stage-label">OCR tier</label>
            <select
              className="instruction-input settings-select"
              value={form.ocr_tier}
              onChange={(e) => setStr("ocr_tier", e.target.value)}
            >
              <option value="small">Small (fast, lower accuracy)</option>
              <option value="medium">Medium</option>
              <option value="high">High (slow, best accuracy)</option>
            </select>
          </div>
          <div className="settings-stage-row">
            <label className="settings-stage-label">Chunk size (chars)</label>
            <input
              className="instruction-input"
              type="number"
              min={200}
              value={form.chunk_target_chars}
              onChange={(e) => setNum("chunk_target_chars", e.target.value)}
            />
          </div>
          <div className="settings-stage-row">
            <label className="settings-stage-label">Chunk overlap (chars)</label>
            <input
              className="instruction-input"
              type="number"
              min={0}
              value={form.chunk_overlap_chars}
              onChange={(e) => setNum("chunk_overlap_chars", e.target.value)}
            />
          </div>
          <div className="settings-stage-row">
            <label className="settings-stage-label">Max full-read pages</label>
            <input
              className="instruction-input"
              type="number"
              min={1}
              value={form.max_full_read_pages}
              onChange={(e) => setNum("max_full_read_pages", e.target.value)}
            />
          </div>
          <div className="settings-stage-row">
            <label className="settings-stage-label">Min chars/page (text quality)</label>
            <input
              className="instruction-input"
              type="number"
              min={0}
              value={form.min_text_chars_per_page}
              onChange={(e) => setNum("min_text_chars_per_page", e.target.value)}
            />
          </div>
        </div>
      </section>

      <details className="settings-advanced">
        <summary className="settings-advanced-summary">Per-stage model overrides</summary>
        <div className="settings-stage-grid">
          {STAGE_FIELDS.map(({ key, label }) => (
            <div key={key} className="settings-stage-row">
              <label className="settings-stage-label">{label}</label>
              <input
                className="instruction-input"
                placeholder="Inherits default model"
                value={form[key] as string}
                onChange={(e) => setStr(key, e.target.value)}
              />
            </div>
          ))}
        </div>
      </details>

      {error && <p className="error-text">{error}</p>}
      {saved && <p className="settings-saved">Settings saved.</p>}

      <button className="btn-primary" onClick={handleSave} disabled={saving}>
        {saving ? "Saving..." : "Save settings"}
      </button>
    </div>
  );
}
