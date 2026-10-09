import { OrbCursor, OrbLoader } from '../orb/orbPresence';
import { useEffect, useState } from 'react';
import NoCampaign from '../campaign/NoCampaign';
import { getBoard } from '../campaign/lib/api';
import { humanize, prettyText, when } from '../campaign/lib/format';
import { useCurrent } from '../campaign/lib/current';

// S11: the audit trail the server keeps for this campaign: who did what, when.
const ChangeLog = ({ id }) => {
  const cur = useCurrent();
  // The route can name the campaign (#/log/<id>); otherwise the one chosen on Home.
  const cid = id || cur.id;
  const sample = String(cid || '').startsWith('demo-');
  const [events, setEvents] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!cid) return undefined;
    let live = true;
    getBoard(cid).then((b) => live && setEvents(b.events)).catch((e) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [cid]);

  if (!cid) return <NoCampaign what="the change log" />;
  return (
    <section className="card">
      <h2 className="font-semibold">Change log</h2>
      {sample && <p className="mt-2 rounded-xl bg-ink/5 px-3 py-2 text-xs text-ink/70">Sample data. This trail was seeded for a UI walkthrough, not real activity.</p>}
      {error && <p role="alert" className="mt-2 text-sm text-bad">{error}</p>}
      {events === null && !error && <OrbLoader kind="loading" label="Loading the change log" className="mx-auto w-fit rounded-2xl bg-white" />}
      {events?.length === 0 && <p className="mt-2 text-sm text-ink/55">Nothing has happened yet.</p>}
      <ol className="mt-3 flex flex-col gap-2">
        {events?.map((e) => (
          <li key={e.id} className="flex flex-wrap items-baseline gap-x-3 rounded-xl bg-ink/5 px-3 py-2 text-sm">
            <time className="text-xs text-ink/50">{when(e.ts)}</time>
            <span className="font-semibold">{humanize(e.action)}</span>
            <span className="text-xs text-ink/55">by {e.actor}</span>
            {String(e.campaign_id || '').startsWith('demo-') && <span className="rounded-full border border-ink/20 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink/55">Sample</span>}
            {e.detail && <span className="w-full text-ink/70">{prettyText(e.detail)}</span>}
          </li>
        ))}
      </ol>
    </section>
  );
};

export default ChangeLog;
