'use client';

import { useState } from 'react';
import { adminPut } from '@/lib/api';
import type { SiteSettings, StepsContent, FooterContent, CtaContent, SectionCopy } from '@/lib/types';
import {
  Card,
  Field,
  SaveButton,
  TextArea,
  TextInput,
} from './ui';

type SectionKey = 'footer' | 'cta' | 'steps' | 'markets_section' | 'dashboard_section';

const SECTIONS: { key: SectionKey; label: string }[] = [
  { key: 'markets_section', label: 'Markets section' },
  { key: 'dashboard_section', label: 'Dashboard section' },
  { key: 'steps', label: 'How it works' },
  { key: 'cta', label: 'Call-to-action' },
  { key: 'footer', label: 'Footer' },
];

const EMPTY_SECTION: SectionCopy = { kicker: '', title: '', description: '' };

export default function FooterEditor({
  settings,
}: {
  settings: SiteSettings;
}) {
  const [section, setSection] = useState<SectionKey>('markets_section');

  const [footer, setFooter] = useState<FooterContent>(settings.footer);
  const [cta, setCta] = useState<CtaContent>(settings.cta);
  const [steps, setSteps] = useState<StepsContent>(settings.steps);
  const [marketsSection, setMarketsSection] = useState<SectionCopy>(settings.markets_section ?? EMPTY_SECTION);
  const [dashboardSection, setDashboardSection] = useState<SectionCopy>(settings.dashboard_section ?? EMPTY_SECTION);

  const [dirty, setDirty] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);

  function mark(key: SectionKey) {
    setDirty((m) => ({ ...m, [key]: true }));
  }

  async function save(key: SectionKey, payload: unknown) {
    setError(null);
    try {
      await adminPut('/settings', { [key]: payload });
      setDirty((m) => ({ ...m, [key]: false }));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed');
    }
  }

  function renderSectionCopy(
    key: 'markets_section' | 'dashboard_section',
    state: SectionCopy,
    setState: React.Dispatch<React.SetStateAction<SectionCopy>>,
  ) {
    return (
      <Card title={key === 'markets_section' ? 'Markets section heading' : 'Dashboard section heading'}>
        <Field label="Kicker">
          <TextInput value={state.kicker} onChange={(v) => { setState({ ...state, kicker: v }); mark(key); }} />
        </Field>
        <Field label="Title">
          <TextInput value={state.title} onChange={(v) => { setState({ ...state, title: v }); mark(key); }} />
        </Field>
        <Field label="Description">
          <TextArea value={state.description} onChange={(v) => { setState({ ...state, description: v }); mark(key); }} rows={3} />
        </Field>
        <SaveButton onSave={() => save(key, state)} dirty={!!dirty[key]} />
      </Card>
    );
  }

  return (
    <div className="admin-stack">
      {error && <div className="admin-error">{error}</div>}

      <div className="admin-seg">
        {SECTIONS.map((s) => (
          <button
            key={s.key}
            className={section === s.key ? 'is-active' : ''}
            onClick={() => setSection(s.key)}
          >
            {s.label}
          </button>
        ))}
      </div>

      {section === 'markets_section' &&
        renderSectionCopy('markets_section', marketsSection, setMarketsSection)}

      {section === 'dashboard_section' &&
        renderSectionCopy('dashboard_section', dashboardSection, setDashboardSection)}

      {section === 'steps' && (
        <Card title="How it works">
          <div className="admin-grid admin-grid--2">
            <Field label="Kicker">
              <TextInput value={steps.kicker} onChange={(v) => { setSteps({ ...steps, kicker: v }); mark('steps'); }} />
            </Field>
            <Field label="Title">
              <TextInput value={steps.title} onChange={(v) => { setSteps({ ...steps, title: v }); mark('steps'); }} />
            </Field>
          </div>
          <Field label="Intro description">
            <TextArea value={steps.description} onChange={(v) => { setSteps({ ...steps, description: v }); mark('steps'); }} rows={2} />
          </Field>

          <h3 className="admin-card-title" style={{ marginTop: 20 }}>Steps</h3>
          {steps.items.map((item, i) => (
            <div key={i} className="admin-card" style={{ marginBottom: 12 }}>
              <div className="admin-grid admin-grid--3">
                <Field label="Number">
                  <TextInput value={item.num} onChange={(v) => { const items = [...steps.items]; items[i] = { ...item, num: v }; setSteps({ ...steps, items }); mark('steps'); }} />
                </Field>
                <Field label="Title">
                  <TextInput value={item.title} onChange={(v) => { const items = [...steps.items]; items[i] = { ...item, title: v }; setSteps({ ...steps, items }); mark('steps'); }} />
                </Field>
              </div>
              <Field label="Body">
                <TextArea value={item.body} onChange={(v) => { const items = [...steps.items]; items[i] = { ...item, body: v }; setSteps({ ...steps, items }); mark('steps'); }} rows={2} />
              </Field>
            </div>
          ))}
          <SaveButton onSave={() => save('steps', steps)} dirty={!!dirty['steps']} />
        </Card>
      )}

      {section === 'cta' && (
        <Card title="Call-to-action band">
          <Field label="Title">
            <TextInput value={cta.title} onChange={(v) => { setCta({ ...cta, title: v }); mark('cta'); }} />
          </Field>
          <Field label="Description">
            <TextArea value={cta.description} onChange={(v) => { setCta({ ...cta, description: v }); mark('cta'); }} rows={3} />
          </Field>
          <Field label="Button text">
            <TextInput value={cta.button} onChange={(v) => { setCta({ ...cta, button: v }); mark('cta'); }} />
          </Field>
          <SaveButton onSave={() => save('cta', cta)} dirty={!!dirty['cta']} />
        </Card>
      )}

      {section === 'footer' && (
        <Card title="Footer">
          <Field label="Tagline">
            <TextArea value={footer.tagline} onChange={(v) => { setFooter({ ...footer, tagline: v }); mark('footer'); }} rows={2} />
          </Field>
          <div className="admin-grid admin-grid--2">
            <Field label="Copyright line">
              <TextInput value={footer.copyright} onChange={(v) => { setFooter({ ...footer, copyright: v }); mark('footer'); }} />
            </Field>
            <Field label="Disclaimer line">
              <TextInput value={footer.disclaimer} onChange={(v) => { setFooter({ ...footer, disclaimer: v }); mark('footer'); }} />
            </Field>
          </div>

          <h3 className="admin-card-title" style={{ marginTop: 20 }}>Link columns</h3>
          {footer.columns.map((col, ci) => (
            <div key={ci} className="admin-card" style={{ marginBottom: 12 }}>
              <Field label={`Column ${ci + 1} — title`}>
                <TextInput value={col.title} onChange={(v) => { const columns = [...footer.columns]; columns[ci] = { ...col, title: v }; setFooter({ ...footer, columns }); mark('footer'); }} />
              </Field>
              {col.links.map((link, li) => (
                <div key={li} className="admin-grid admin-grid--2" style={{ marginTop: 10 }}>
                  <TextInput value={link.label} placeholder="Label" onChange={(v) => { const columns = [...footer.columns]; const links = [...columns[ci].links]; links[li] = { ...link, label: v }; columns[ci] = { ...columns[ci], links }; setFooter({ ...footer, columns }); mark('footer'); }} />
                  <TextInput value={link.href} placeholder="#markets" onChange={(v) => { const columns = [...footer.columns]; const links = [...columns[ci].links]; links[li] = { ...link, href: v }; columns[ci] = { ...columns[ci], links }; setFooter({ ...footer, columns }); mark('footer'); }} />
                </div>
              ))}
            </div>
          ))}
          <SaveButton onSave={() => save('footer', footer)} dirty={!!dirty['footer']} />
        </Card>
      )}
    </div>
  );
}
