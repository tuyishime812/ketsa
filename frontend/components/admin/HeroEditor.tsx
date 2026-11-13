'use client';

import { useEffect, useState } from 'react';
import { adminPut } from '@/lib/api';
import type { Proof, SiteSettings } from '@/lib/types';
import {
  Card,
  Field,
  NumberInput,
  SaveButton,
  TextArea,
  TextInput,
} from './ui';

export default function HeroEditor({
  proof,
  settings,
}: {
  proof: Proof | null;
  settings: SiteSettings;
}) {
  const [hero, setHero] = useState(settings.hero);
  const [proofDraft, setProofDraft] = useState<Proof | null>(proof);
  const [error, setError] = useState<string | null>(null);
  const [heroDirty, setHeroDirty] = useState(false);
  const [proofDirty, setProofDirty] = useState(false);

  useEffect(() => {
    setHero(settings.hero);
    setHeroDirty(false);
  }, [settings]);

  useEffect(() => {
    setProofDraft(proof);
    setProofDirty(false);
  }, [proof]);

  function patch(p: Partial<SiteSettings['hero']>) {
    setHero((h) => ({ ...h, ...p }));
    setHeroDirty(true);
  }

  function patchProof(p: Partial<Proof>) {
    setProofDraft((prev) => (prev ? { ...prev, ...p } : prev));
    setProofDirty(true);
  }

  async function saveHero() {
    setError(null);
    try {
      await adminPut('/settings/hero', hero);
      setHeroDirty(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed');
      throw err;
    }
  }

  async function saveProof() {
    if (!proofDraft) return;
    setError(null);
    try {
      await adminPut('/proof', proofDraft);
      setProofDirty(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed');
      throw err;
    }
  }

  return (
    <div className="admin-stack">
      {error && <div className="admin-error">{error}</div>}

      <Card title="Hero — small badge (top of Hero)">
        <Field label="Badge text">
          <TextInput
            value={hero.badge}
            onChange={(v) => patch({ badge: v })}
            placeholder="$97.4M traded this week"
          />
        </Field>
      </Card>

      <Card title="Hero — headline">
        <div className="admin-grid admin-grid--2">
          <Field label="Headline part 1 (before accent)">
            <TextInput value={hero.headline_1} onChange={(v) => patch({ headline_1: v })} />
          </Field>
          <Field label="Headline accent (italic blue part)">
            <TextInput value={hero.headline_accent} onChange={(v) => patch({ headline_accent: v })} />
          </Field>
        </div>
        <Field label="Description paragraph">
          <TextArea value={hero.description} onChange={(v) => patch({ description: v })} rows={4} />
        </Field>
        <SaveButton onSave={saveHero} dirty={heroDirty} />
      </Card>

      {proofDraft && (
        <Card title="Proof stats — numbers counted up in the hero">
          <div className="admin-grid admin-grid--3">
            <Field label="Traders (in thousands)">
              <NumberInput value={proofDraft.traders_k} onChange={(v) => patchProof({ traders_k: v })} />
            </Field>
            <Field label="Live markets">
              <NumberInput value={proofDraft.live_markets} onChange={(v) => patchProof({ live_markets: v })} />
            </Field>
            <Field label="Total volume (in $M)">
              <NumberInput value={proofDraft.total_volume_m} onChange={(v) => patchProof({ total_volume_m: v })} />
            </Field>
          </div>
          <SaveButton onSave={saveProof} dirty={proofDirty} />
        </Card>
      )}

      <p className="admin-hint">These fields update the hero section on the homepage.</p>
    </div>
  );
}
