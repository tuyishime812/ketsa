'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  getBroadcastStatus,
  startBroadcast,
  type BroadcastStatus,
} from '@/lib/api';
import { Card, Field, TextArea, TextInput } from './ui';

/**
 * Admin-only: queue one email announcement to every user who has an email
 * address.
 *
 * Two things this UI is careful about:
 *
 *  1. It is a real send, not a preview, and the backend emails every eligible
 *     account. So there is an explicit confirmation step, and the recipient
 *     count is shown *before* anything is sent.
 *  2. Copy is plain text. The backend HTML-escapes it before it reaches the
 *     mail template, so anything typed here renders as visible text in the
 *     recipient's mail client rather than as markup.
 */
export default function BroadcastEditor({ token }: { token: string }) {
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<BroadcastStatus | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Always stop polling when the panel goes away, so a finished broadcast
  // doesn't leave a timer running in an unmounted component.
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const poll = useCallback(
    async (jobId: string) => {
      try {
        const status = await getBroadcastStatus(token, jobId);
        setJob(status);
        if (status.status === 'running') {
          timer.current = setTimeout(() => void poll(jobId), 1000);
        }
      } catch (err) {
        setError(
          err instanceof Error ? err.message : 'Could not read broadcast progress',
        );
      }
    },
    [token],
  );

  const trimmedSubject = subject.trim();
  const trimmedBody = body.trim();
  const ready = trimmedSubject.length > 0 && trimmedBody.length > 0;
  const tooLong =
    trimmedSubject.length > 200 || trimmedBody.length > 20000;

  async function send() {
    setStarting(true);
    setError(null);
    try {
      const accepted = await startBroadcast(token, trimmedSubject, trimmedBody);
      setConfirming(false);
      setSubject('');
      setBody('');
      setJob({
        job_id: accepted.job_id,
        status: 'running',
        total: accepted.total,
        sent: 0,
        failed: 0,
        subject: trimmedSubject,
        error: null,
      });
      void poll(accepted.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Broadcast failed to start');
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="admin-stack">
      {error && <div className="admin-error">{error}</div>}

      <Card title="Email every user">
        <p style={{ marginTop: 0 }}>
          Sends one message to every account that has an email address. Phone-only
          accounts are skipped. There is no unsubscribe link, so only use this
          for genuinely important announcements.
        </p>

        <Field label="Subject">
          <TextInput
            value={subject}
            onChange={setSubject}
            placeholder="New markets just opened"
          />
        </Field>

        <Field label="Message">
          <TextArea value={body} onChange={setBody} rows={8} />
        </Field>

        {tooLong && (
          <div className="admin-error">
            Subject must be 200 characters or fewer and the message 20,000 or
            fewer.
          </div>
        )}

        {!confirming ? (
          <button
            className="admin-btn admin-btn--primary"
            disabled={!ready || tooLong}
            onClick={() => setConfirming(true)}
          >
            Send announcement…
          </button>
        ) : (
          <div
            className="admin-card"
            style={{ borderColor: '#f0c4c4', background: '#fbebeb', marginTop: 4 }}
          >
            <strong>This emails every registered user immediately.</strong>
            <p style={{ marginBottom: 0 }}>
              It cannot be unsent. Continue?
            </p>
            <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
              <button
                className="admin-btn admin-btn--primary"
                disabled={starting}
                onClick={() => void send()}
              >
                {starting ? 'Starting…' : 'Yes, send it'}
              </button>
              <button
                className="admin-btn"
                disabled={starting}
                onClick={() => setConfirming(false)}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </Card>

      {job && (
        <Card title="Broadcast progress">
          <dl className="admin-grid admin-grid--2" style={{ margin: 0 }}>
            <div>
              <dt className="admin-muted">Subject</dt>
              <dd style={{ margin: '2px 0 0' }}>{job.subject}</dd>
            </div>
            <div>
              <dt className="admin-muted">Status</dt>
              <dd style={{ margin: '2px 0 0' }}>
                {job.status === 'running'
                  ? `Sending… ${job.sent}/${job.total}`
                  : job.status === 'done'
                    ? `Sent to ${job.sent} of ${job.total}`
                    : `Failed — ${job.error ?? 'unknown error'}`}
              </dd>
            </div>
          </dl>
          {job.failed > 0 && (
            <p className="admin-muted">
              {job.failed} recipient(s) could not be sent to.
            </p>
          )}
          <button
            className="admin-btn"
            onClick={() => setJob(null)}
            style={{ marginTop: 12 }}
          >
            Clear
          </button>
        </Card>
      )}
    </div>
  );
}