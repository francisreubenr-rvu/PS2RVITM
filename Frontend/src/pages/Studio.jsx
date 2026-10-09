import { Mic, Briefcase, Rocket, ArrowRight, Check } from 'lucide-react';
import { CardTitle, Banner } from '../components/ui';
import { DELIVERABLES, PIPELINES } from '../data/studio';
import { useStore } from '../state/store';
import { navigate } from '../lib/router';

// S15: choose what to make. Posts, posters and WhatsApp run through the campaign pipeline; names, taglines and the
// brand kit through the identity flow; website and video are separate services (docs/screen-flow.md).
const Studio = () => {
  const { state, dispatch } = useStore();
  const { mode, selected } = state.studio;
  const set = (patch) => dispatch({ type: 'SET_STUDIO', patch });
  const toggle = (id) => set({ selected: selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id] });

  const chosen = DELIVERABLES.filter((d) => selected.includes(d.id));
  const byPipeline = chosen.reduce((acc, d) => ({ ...acc, [d.pipeline]: [...(acc[d.pipeline] ?? []), d] }), {});
  const external = chosen.filter((d) => !PIPELINES[d.pipeline].backend);

  const start = () => {
    if (mode === 'new') return navigate('launch');
    const first = chosen[0];
    navigate(first ? first.slug : 'voice');
  };

  return (
    <div className="flex flex-col gap-4">
      <section className="grid gap-3 sm:grid-cols-2">
        {[
          { id: 'have', icon: Briefcase, title: 'I have a business', body: 'Make posts, posters, a website or a reel for what you already sell.' },
          { id: 'new', icon: Rocket, title: "I don't have a business yet", body: 'Start from zero. Get ideas, a name, a brand and a launch pack.' },
        ].map((p) => (
          <button
            key={p.id}
            type="button"
            aria-pressed={mode === p.id}
            onClick={() => set({ mode: p.id })}
            className={`flex items-start gap-3 rounded-2xl p-5 text-left transition-colors ${mode === p.id ? 'bg-accent text-on-accent' : 'bg-card text-ink hover:bg-white'}`}
          >
            <span className={`grid size-11 shrink-0 place-items-center rounded-xl ${mode === p.id ? 'bg-ink/10' : 'bg-accent-soft text-accent-deep'}`}>
              <p.icon size={22} />
            </span>
            <span>
              <span className="block font-semibold">{p.title}</span>
              <span className={`mt-1 block text-sm ${mode === p.id ? 'opacity-75' : 'text-ink/60'}`}>{p.body}</span>
            </span>
          </button>
        ))}
      </section>

      {mode === 'new' ? (
        <section className="card">
          <CardTitle sub="You answer a few questions; the builder suggests what to start and prepares everything you need to launch.">
            Build my business
          </CardTitle>
          <ul className="mb-4 grid gap-2 text-sm sm:grid-cols-2">
            {['Business ideas that fit your skills and budget', 'Name and taglines in English, Hindi and Kannada', 'Brand colours, starter logos and voice', 'Menu, prices and an opening offer', 'Opening posts, poster, website and reel'].map((t) => (
              <li key={t} className="flex items-start gap-2"><Check size={16} className="mt-0.5 shrink-0 text-good" />{t}</li>
            ))}
          </ul>
          <button type="button" onClick={start} className="btn-primary">Start <ArrowRight size={16} /></button>
        </section>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
          <section className="card">
            <CardTitle sub="Pick everything you want. You can also say it out loud on the next screen.">What do you want to make?</CardTitle>
            <div className="grid gap-2.5 sm:grid-cols-2">
              {DELIVERABLES.filter((d) => d.id !== 'plan').map((d) => {
                const on = selected.includes(d.id);
                return (
                  <button
                    key={d.id}
                    type="button"
                    aria-pressed={on}
                    onClick={() => toggle(d.id)}
                    title={PIPELINES[d.pipeline].backend ? undefined : 'No backend yet'}
                    className={`flex cursor-pointer items-start gap-3 rounded-2xl border p-3.5 text-left transition-colors ${PIPELINES[d.pipeline].backend ? '' : 'opacity-50'} ${on ? 'border-accent bg-accent-soft' : 'border-ink/25 bg-white/85 text-ink hover:border-ink/45 hover:bg-white focus-visible:border-ink/60 focus-visible:bg-white'}`}
                  >
                    <span className={`mt-0.5 grid size-5 shrink-0 place-items-center rounded-md border ${on ? 'border-accent bg-accent text-on-accent' : 'border-ink/30'}`}>
                      {on && <Check size={13} />}
                    </span>
                    <span className="min-w-0">
                      <span className="flex flex-wrap items-center gap-2 font-medium">{d.label}</span>
                      <span className="mt-0.5 block text-xs text-ink/55">{d.desc}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          </section>

          <section className="card flex flex-col">
            <CardTitle sub="Where each item is made.">Your pack</CardTitle>
            {chosen.length === 0 ? (
              <p className="text-sm text-ink/55">Nothing selected yet.</p>
            ) : (
              <ul className="flex flex-col gap-3 text-sm">
                {Object.entries(byPipeline).map(([key, items]) => (
                  <li key={key}>
                    <p className={`font-medium ${PIPELINES[key].backend ? '' : 'opacity-50'}`}>{PIPELINES[key].label}</p>
                    <p className="text-ink/60">{items.map((i) => i.label).join(', ')}</p>
                  </li>
                ))}
              </ul>
            )}
            {external.length > 0 && (
              <div className="mt-4">
                <Banner tone="warn">{external.map((e) => e.label).join(' and ')} have no backend yet. You can design them here; generation turns on when they are connected.</Banner>
              </div>
            )}
            <button type="button" disabled={chosen.length === 0} onClick={start} className="btn-primary mt-auto self-start">
              <Mic size={16} /> Start with the first item
            </button>
          </section>
        </div>
      )}
    </div>
  );
};

export default Studio;
