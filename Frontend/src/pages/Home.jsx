import { useEffect, useState } from 'react';
import { Mic, Sparkles, Rocket, Store, Bot } from 'lucide-react';
import StatCards from '../components/dashboard/StatCards';
import { SectionTitle } from '../components/ui';
import { listOverview, startInterview, getDashboard } from '../campaign/lib/api';
import { MAIN_LANGS, MORE_LANGS, humanize } from '../campaign/lib/format';
import { go, setCurrent, useCurrent } from '../campaign/lib/current';
import { navigate } from '../lib/router';
import { OrbCursor, OrbLoader } from '../orb/orbPresence';

const nameOf = (b) => (!b ? '' : typeof b === 'string' ? b : b.name || '');
const nextStage = (status) => (status === 'draft' || status === 'planned' ? 'plan' : 'campaign');

// S2: start a campaign, see every campaign and what the current one needs. All numbers come from the API.
const Home = () => {
  const cur = useCurrent();
  const [rows, setRows] = useState(null);
  const [totals, setTotals] = useState(null);
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(null);
  const [totalsBusy, setTotalsBusy] = useState(false);

  useEffect(() => {
    let live = true;
    listOverview()
      .then((res) => {
        if (!live) return;
        setRows(
          Array.isArray(res)
            ? res.map((r) => ({ id: r.campaign_id, name: nameOf(r.business), status: r.status, totals: r.totals }))
            : res.legacy.map((c) => ({ id: c.id, name: c.transcript.slice(0, 48), status: c.status, totals: {} }))
        );
      })
      .catch((e) => {
        if (live) {
          setError(e.message);
          setRows([]);
        }
      });
    return () => {
      live = false;
    };
  }, []);

  const activeId = cur.id || rows?.[0]?.id;
  useEffect(() => {
    if (!activeId) return undefined;
    let live = true;
    setTotalsBusy(true);
    getDashboard(activeId)
      .then((d) => live && setTotals(d.totals))
      .catch(() => live && setTotals(null))
      .finally(() => live && setTotalsBusy(false));
    return () => {
      live = false;
    };
  }, [activeId]);

  const start = async (lang) => {
    setStarting(lang);
    setError('');
    try {
      const s = await startInterview(lang);
      go({ name: 'talk', sid: s.id });
    } catch (e) {
      setError(e.message);
      setStarting(null);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <section data-tour="start" className="rounded-2xl bg-white p-5 text-ink">
        <p className="text-sm font-semibold text-accent-deep">Campaign for your shop</p>
        <h1 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">Say the offer. We write the campaign.</h1>
        <p className="mt-2 max-w-xl text-sm text-ink/65">Answer a few questions out loud or by tapping. Nothing goes out that is not what you said.</p>
        <div role="group" aria-label="Start in a language" className="mt-4 flex flex-wrap gap-2">
          {MAIN_LANGS.map((l, i) => (
            <button key={l.code} type="button" disabled={starting !== null} onClick={() => start(l.code)} className={i === 0 ? 'btn-primary' : 'btn-ghost'}>
              <Mic size={16} /> {starting === l.code ? 'Starting' : `Start in ${l.native}`}
              <OrbCursor active={starting === l.code} kind="thinking" label="Starting the conversation" />
            </button>
          ))}
          <select aria-label="Start in another language" className="field h-10 w-auto" value="" disabled={starting !== null} onChange={(e) => e.target.value && start(e.target.value)}>
            <option value="">More languages</option>
            {MORE_LANGS.map((l) => <option key={l.code} value={l.code}>{l.native} ({l.name}, draft)</option>)}
          </select>
        </div>
        <button type="button" onClick={() => navigate('agent')} className="mt-3 flex items-center gap-2 text-sm font-semibold text-accent-deep hover:underline">
          <Bot size={16} /> Or describe it once and let the agent plan the work
        </button>
        {error && (
          <p role="alert" className="mt-3 text-sm text-bad">
            {error}
          </p>
        )}
      </section>

      <section className="grid gap-3 sm:grid-cols-2">
        <button type="button" onClick={() => navigate('studio')} className="flex items-center gap-3 rounded-2xl bg-white p-4 text-left text-ink hover:bg-white/90">
          <span className="grid size-11 place-items-center rounded-xl bg-accent-soft text-accent-deep">
            <Sparkles size={22} />
          </span>
          <span>
            <span className="block font-semibold">Make something new</span>
            <span className="text-sm text-ink/60">Posts, posters, taglines, a website or a reel.</span>
          </span>
        </button>
        <button type="button" onClick={() => navigate('launch')} className="flex items-center gap-3 rounded-2xl bg-accent p-4 text-left text-on-accent hover:bg-accent-hover">
          <span className="grid size-11 place-items-center rounded-xl bg-ink/10">
            <Rocket size={22} />
          </span>
          <span>
            <span className="block font-semibold">No business yet? Build one</span>
            <span className="text-sm opacity-75">Ideas, a name, a brand and a launch pack.</span>
          </span>
        </button>
      </section>

      {totalsBusy && <OrbLoader kind="loading" size={20} label="Reading this campaign's numbers" className="w-fit flex-row rounded-full bg-white" style={{ padding: '0.25rem 0.75rem' }} />}
      {activeId && <StatCards totals={totals} id={activeId} />}

      <section>
        <SectionTitle>Campaigns</SectionTitle>
        {rows === null && <OrbLoader kind="loading" label="Loading campaigns" className="rounded-2xl bg-white" />}
        {rows?.length === 0 && !error && (
          <p className="rounded-2xl border border-dashed border-white/20 p-5 text-sm text-white/70">No campaigns yet. Start one above. It appears here once the conversation is finished.</p>
        )}
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {rows?.map((c) => {
            const on = c.id === activeId;
            const t = c.totals || {};
            return (
              <button
                key={c.id}
                type="button"
                onClick={() => {
                  setCurrent({ id: c.id, business: c.name });
                  go({ name: nextStage(c.status), id: c.id });
                }}
                aria-pressed={on}
                className={`flex items-start justify-between gap-3 rounded-2xl p-4 text-left transition-colors ${on ? 'bg-accent text-on-accent' : 'bg-card text-ink hover:bg-white'}`}
              >
                <span className="min-w-0">
                  <span className="block truncate font-semibold">{c.name || `Campaign ${c.id.slice(0, 6)}`}</span>
                  <span className={`mt-1 block text-xs ${on ? 'opacity-75' : 'text-ink/55'}`}>
                    {t.assets ?? 0} assets, {t.approved ?? 0} approved, {t.clicks ?? 0} clicks
                  </span>
                  <span className={`mt-3 inline-block rounded-full px-2.5 py-0.5 text-[11px] font-medium ${on ? 'bg-ink text-accent' : 'bg-ink/5 text-ink/70'}`}>{humanize(c.status)}</span>
                </span>
                <span className={`grid size-12 shrink-0 place-items-center rounded-full ${on ? 'bg-ink/10' : 'bg-accent-soft text-accent-deep'}`}>
                  <Store size={22} />
                </span>
              </button>
            );
          })}
        </div>
      </section>
    </div>
  );
};

export default Home;
