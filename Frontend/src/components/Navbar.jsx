import { useEffect, useState } from 'react';
import { Menu, Mic, Lock, PanelRightOpen } from 'lucide-react';
import { SyncDot, ProviderChip } from './ui';
import { getPlan, health } from '../campaign/lib/api';
import { useCurrent } from '../campaign/lib/current';
import { useAuth } from '../lib/auth';
import NotificationsMenu from './NotificationsMenu';
import { openTalk } from './talk/useTalk';
import { OrbCursor } from '../orb/orbPresence';

const greeting = () => {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 17) return 'Good afternoon';
  return 'Good evening';
};

const POOL = { token_plan: 'Agnes, token plan', free: 'Agnes, free tier' };

// AppShell top bar: page title, campaign name, plan state, sync dot and provider chip (docs/frontend.prd.md section 4).
// Everything here is read from the API; nothing is a placeholder.
const Navbar = ({ page, onSelect, onOpenMenu, onOpenSummary }) => {
  const { id, business } = useCurrent();
  const { me } = useAuth();
  const user = me?.user;
  const first = user?.name?.split(' ')[0];
  const [status, setStatus] = useState(null); // null while loading, false when unreachable
  const [locked, setLocked] = useState(null);
  const isHome = page.slug === 'home';

  useEffect(() => {
    let live = true;
    const ping = () => health().then((h) => live && setStatus(h)).catch(() => live && setStatus(false));
    ping();
    const t = setInterval(ping, 15000);
    return () => {
      live = false;
      clearInterval(t);
    };
  }, []);

  useEffect(() => {
    setLocked(null);
    if (!id) return undefined;
    let live = true;
    getPlan(id).then((p) => live && setLocked(p.status === 'locked')).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [id, page.slug]);

  const provider = status ? (status.agnes_configured ? POOL[status.agnes_key_pool] || 'Agnes' : 'Agnes not connected') : 'Server unreachable';
  const sync = status ? 'connected' : status === false ? 'offline' : 'reconnecting';

  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="flex min-w-0 items-start gap-2">
        <button type="button" aria-label="Open menu" onClick={onOpenMenu} data-tour="menu" className="-ml-2 grid size-10 shrink-0 place-items-center rounded-xl text-white/80 hover:bg-white/10 lg:hidden">
          <Menu size={20} />
        </button>
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">{isHome ? `${greeting()}${first ? `, ${first}` : business ? `, ${business}` : ''}` : page.label}</h1>
          <p className="mt-0.5 max-w-xl text-sm text-white/55">{isHome ? 'Your campaigns and what needs you next.' : page.description}</p>
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            {locked !== null && page.slug !== 'voice' && (
              <span className="inline-flex items-center gap-1 rounded-full bg-white/10 px-2.5 py-1 text-xs font-medium text-white/80">
                <Lock size={11} className="text-accent" /> {locked ? 'Facts locked' : 'Plan not locked yet'}
              </span>
            )}
            <ProviderChip name={provider} />
            <SyncDot state={sync} />
            {status === null && <span className="rounded-full bg-white"><OrbCursor active kind="searching" label="Reaching the server" /></span>}
          </div>
        </div>
      </div>

      <div className="ml-auto flex items-center gap-2">
        <NotificationsMenu user={user} />
        <button
          type="button"
          onClick={() => openTalk('greet')}
          data-tour="mic"
          aria-label="Talk to GrowIt"
          title="Talk to GrowIt"
          className="voice-mic voice-mic-dark voice-mic-sm grid size-10 place-items-center rounded-full"
        >
          <Mic size={18} />
        </button>
        <button
          type="button"
          onClick={onOpenSummary}
          data-tour="summary"
          aria-label="Open the calendar panel"
          title="Calendar and next up"
          className="grid size-10 place-items-center rounded-full bg-black/25 text-white/70 ring-1 ring-white/10 transition-colors hover:text-white xl:hidden"
        >
          <PanelRightOpen size={18} />
        </button>
      </div>
    </header>
  );
};

export default Navbar;
