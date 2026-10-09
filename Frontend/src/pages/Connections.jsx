import { useCallback, useEffect, useState } from 'react';
import { Camera, Play, MessageCircle, ThumbsUp, RefreshCw, Unlink, TriangleAlert, Check, Copy, Heart, MessageSquare } from 'lucide-react';
import { API_URL, api } from '../campaign/lib/api';
import { navigate } from '../lib/router';
import { OrbCursor, OrbLoader } from '../orb/orbPresence';

// What each notice code from the login round trip means. The server sends the owner back to #/connections/<code>.
const NOTICES = {
  connected: { tone: 'good', text: 'Connected.' },
  denied: { tone: 'warn', text: 'You cancelled the sign-in, so nothing was connected.' },
  failed: { tone: 'bad', text: 'The sign-in did not finish. Please try again.' },
  expired: { tone: 'bad', text: 'The service no longer accepts the saved login. Connect again.' },
  not_business: { tone: 'bad', text: 'That Instagram account is a personal one. Switch it to a Business or Creator account in Instagram, then connect again.' },
  'youtube-connected': { tone: 'good', text: 'YouTube connected.' },
  'youtube-denied': { tone: 'warn', text: 'You cancelled the YouTube sign-in, so nothing was connected.' },
  'youtube-scope': { tone: 'bad', text: 'YouTube was not connected because the upload permission was unticked. Connect again and leave every box ticked.' },
  'youtube-no_channel': { tone: 'bad', text: 'That Google account has no YouTube channel yet. Create one in YouTube, then connect again.' },
  'youtube-failed': { tone: 'bad', text: 'The YouTube sign-in did not finish. Please try again.' },
  'youtube-expired': { tone: 'bad', text: 'YouTube no longer accepts the saved login. Connect again.' },
};
const TONE = { good: 'bg-good/15', warn: 'bg-warn/20', bad: 'bg-bad/15' };

const stat = (v) => (v == null ? 'hidden' : Number(v).toLocaleString('en-IN'));
const when = (iso) => (iso ? new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '');

const Shell = ({ icon: Icon, title, status, tone = 'neutral', children, muted = false }) => (
  <section className={`card flex flex-col gap-3 ${muted ? 'opacity-60' : ''}`}>
    <div className="flex items-start justify-between gap-3">
      <div className="flex min-w-0 items-center gap-3">
        <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent-deep"><Icon size={20} /></span>
        <h2 className="truncate text-base font-semibold">{title}</h2>
      </div>
      <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${tone === 'good' ? 'bg-good/12 text-good' : tone === 'warn' ? 'bg-warn/15 text-warn' : 'bg-ink/8 text-ink/60'}`}>{status}</span>
    </div>
    {children}
  </section>
);

const CopyField = ({ label, value }) => {
  const [done, setDone] = useState(false);
  return (
    <div className="flex items-center gap-2 rounded-xl bg-ink/5 px-3 py-2 text-xs">
      <span className="shrink-0 text-ink/55">{label}</span>
      <code className="min-w-0 flex-1 truncate">{value}</code>
      <button type="button" aria-label={`Copy ${label}`} onClick={() => { try { navigator.clipboard?.writeText(value); setDone(true); setTimeout(() => setDone(false), 1500); } catch { /* clipboard blocked */ } }} className="grid size-7 place-items-center rounded-lg hover:bg-ink/10">
        {done ? <Check size={14} className="text-good" /> : <Copy size={14} />}
      </button>
    </div>
  );
};

const Actions = ({ onRefresh, onDisconnect, busy }) => (
  <div className="flex flex-wrap gap-2">
    <button type="button" disabled={busy} onClick={onRefresh} className="btn-ghost h-9 px-3 text-sm">{busy === 'refresh' ? <OrbCursor active kind="searching" label="Refreshing" /> : <RefreshCw size={14} />} Refresh</button>
    <button type="button" disabled={busy} onClick={onDisconnect} className="btn-ghost h-9 px-3 text-sm">{busy === 'disconnect' ? <OrbCursor active kind="thinking" label="Disconnecting" /> : <Unlink size={14} />} Disconnect</button>
  </div>
);

const useAction = (provider, reload) => {
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const run = async (kind, fn) => {
    setBusy(kind);
    setError('');
    try {
      await fn();
      await reload();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy('');
    }
  };
  return {
    busy, error,
    refresh: () => run('refresh', () => api(`/connections/${provider}/refresh`, { method: 'POST' })),
    disconnect: () => run('disconnect', () => api(`/connections/${provider}`, { method: 'DELETE' })),
  };
};

// Shown instead of a Connect button when the server has no credentials for the service: what is missing and who does what.
const NeedsSetup = ({ missing, steps, redirect }) => (
  <div className="flex flex-col gap-2 text-sm">
    <p className="font-medium">Cannot be connected yet. This server is missing {missing.map((n, i) => <span key={n}>{i > 0 && ' and '}<code>{n}</code></span>)}.</p>
    <ol className="list-decimal space-y-1 pl-5 text-ink/70">{steps.map((s) => <li key={s}>{s}</li>)}</ol>
    {redirect && <CopyField label="Redirect URI" value={redirect} />}
  </div>
);

const Instagram = ({ c, setup, reload }) => {
  const act = useAction('instagram', reload);
  const p = c.profile;
  return (
    <Shell icon={Camera} title="Instagram" status={c.connected ? (c.expired ? 'Login expired' : 'Connected') : c.configured ? 'Not connected' : 'Needs server setup'} tone={c.connected ? (c.expired ? 'warn' : 'good') : c.configured ? 'neutral' : 'warn'}>
      {!c.configured && (
        <NeedsSetup
          missing={c.missing?.length ? c.missing : ['INSTAGRAM_APP_ID', 'INSTAGRAM_APP_SECRET']}
          steps={[
            'The team creates a Meta app with the Instagram product and adds the owner\'s Instagram Business or Creator account as a tester.',
            'Add the redirect URI below to that app. Instagram wants an https address, so use a tunnel when running locally and set INSTAGRAM_REDIRECT_URI to it.',
            'Put the app\'s ID and secret in the server\'s .env, then restart the server. The Connect button appears here.',
          ]}
          redirect={setup.redirect_uri}
        />
      )}
      {c.configured && !c.connected && (
        <>
          <p className="text-sm text-ink/70">You will go to Instagram to sign in and allow read-only access to your profile and recent posts. This works for Business and Creator accounts.</p>
          <a href={`${API_URL}/auth/instagram/login`} className="btn-primary w-fit"><Camera size={15} /> Connect Instagram</a>
        </>
      )}
      {c.connected && (
        <>
          <div className="flex items-center gap-3">
            {p.profile_picture_url ? <img src={p.profile_picture_url} alt="" referrerPolicy="no-referrer" className="size-14 rounded-full" /> : <span className="grid size-14 place-items-center rounded-full bg-accent text-on-accent text-lg font-semibold">{p.username?.[0]?.toUpperCase()}</span>}
            <div className="min-w-0">
              <p className="truncate font-semibold">{p.name || p.username}</p>
              <p className="truncate text-sm text-ink/60">@{p.username} · {String(p.account_type || '').toLowerCase()}</p>
            </div>
          </div>
          <dl className="grid grid-cols-3 divide-x divide-ink/10 rounded-xl bg-ink/5 py-2.5 text-center">
            {[['Followers', p.followers_count], ['Following', p.follows_count], ['Posts', p.media_count]].map(([k, v]) => (
              <div key={k}><dd className="text-lg font-semibold tabular-nums">{stat(v)}</dd><dt className="text-xs text-ink/55">{k}</dt></div>
            ))}
          </dl>
          {p.insights && (
            <dl className="grid grid-cols-3 divide-x divide-ink/10 rounded-xl bg-ink/5 py-2.5 text-center" aria-label={`Last ${p.insights.window_days} days`}>
              {[['Reach', p.insights.reach], ['Profile views', p.insights.profile_views], ['Accounts engaged', p.insights.accounts_engaged]].map(([k, v]) => (
                <div key={k}><dd className="text-lg font-semibold tabular-nums">{stat(v)}</dd><dt className="text-xs text-ink/55">{k}, {p.insights.window_days} days</dt></div>
              ))}
            </dl>
          )}
          {c.media.length > 0 && (
            <div>
              <p className="mb-1.5 text-xs font-medium text-ink/55">Recent posts, read just now</p>
              <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4">
                {c.media.slice(0, 8).map((m) => (
                  <li key={m.id} className="group relative overflow-hidden rounded-xl bg-ink/8">
                    <a href={m.permalink} target="_blank" rel="noopener noreferrer" aria-label={`Open post from ${when(m.timestamp)} on Instagram`} className="block aspect-square">
                      {m.thumbnail ? <img src={m.thumbnail} alt="" loading="lazy" referrerPolicy="no-referrer" className="size-full object-cover" /> : <span className="grid size-full place-items-center p-2 text-center text-[11px] text-ink/50">{m.caption || m.media_type}</span>}
                      <span className="absolute inset-x-0 bottom-0 flex justify-between bg-gradient-to-t from-black/70 to-transparent px-2 pb-1 pt-4 text-[11px] font-medium text-white">
                        <span className="flex items-center gap-1"><Heart size={11} />{stat(m.likes)}</span>
                        <span className="flex items-center gap-1"><MessageSquare size={11} />{stat(m.comments)}</span>
                      </span>
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <p className="text-xs text-ink/55">Read {when(c.fetched_at)}. Login valid until {when(c.expires_at)}. Reach and impressions need a permission this app does not ask for, so Insights shows sample numbers for those.</p>
          {c.expired && <a href={`${API_URL}/auth/instagram/login`} className="btn-primary w-fit"><Camera size={15} /> Connect again</a>}
          <Actions onRefresh={act.refresh} onDisconnect={act.disconnect} busy={act.busy} />
        </>
      )}
      {act.error && <p role="alert" className="text-sm text-bad">{act.error}</p>}
    </Shell>
  );
};

const YouTube = ({ c, setup, reload }) => {
  const act = useAction('youtube', reload);
  const p = c.profile;
  return (
    <Shell icon={Play} title="YouTube" status={c.connected ? 'Connected' : c.configured ? 'Not connected' : 'Needs server setup'} tone={c.connected ? 'good' : c.configured ? 'neutral' : 'warn'}>
      {!c.configured && (
        <NeedsSetup
          missing={c.missing?.length ? c.missing : ['GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET']}
          steps={[
            'The team creates a Google Cloud OAuth client (Web application) and enables the YouTube Data API v3. The same client also serves Google sign-in.',
            'Add the redirect URI below to that client. While the app is in testing, add the owner\'s Google account as a test user.',
            'Put the client ID and secret in the server\'s .env, then restart the server. The Connect button appears here.',
          ]}
          redirect={setup.youtube_redirect_uri}
        />
      )}
      {c.configured && !c.connected && (
        <>
          <p className="text-sm text-ink/70">Post an approved reel to your channel as a YouTube Short. You will go to Google to allow uploading videos and reading your channel.</p>
          <a href={`${API_URL}/auth/youtube/login`} className="btn-primary w-fit"><Play size={15} /> Connect YouTube</a>
        </>
      )}
      {c.connected && (
        <>
          <div className="flex items-center gap-3">
            {p.picture ? <img src={p.picture} alt="" referrerPolicy="no-referrer" className="size-14 rounded-full" /> : <span className="grid size-14 place-items-center rounded-full bg-accent text-on-accent text-lg font-semibold">{p.title?.[0]}</span>}
            <div className="min-w-0"><p className="truncate font-semibold">{p.title}</p><p className="truncate text-sm text-ink/60">{p.handle}</p></div>
          </div>
          <dl className="grid grid-cols-3 divide-x divide-ink/10 rounded-xl bg-ink/5 py-2.5 text-center">
            {[['Subscribers', p.subscribers], ['Videos', p.videos], ['Views', p.views]].map(([k, v]) => (
              <div key={k}><dd className="text-lg font-semibold tabular-nums">{stat(v)}</dd><dt className="text-xs text-ink/55">{k}</dt></div>
            ))}
          </dl>
          <Actions onRefresh={act.refresh} onDisconnect={act.disconnect} busy={act.busy} />
        </>
      )}
      <ul className="list-disc space-y-1 pl-5 text-xs text-ink/60">
        <li>Shorts go up as <strong>private</strong>. Until Google audits this app, YouTube keeps API uploads private even if you ask for public, and the app tells you when that happens.</li>
        <li>About six uploads a day on the default quota.</li>
      </ul>
      {act.error && <p role="alert" className="text-sm text-bad">{act.error}</p>}
    </Shell>
  );
};

const WhatsApp = ({ c }) => (
  <Shell icon={MessageCircle} title="WhatsApp" status="Click to chat" tone="good">
    <p className="text-sm text-ink/70">{c.note}</p>
    <p className="text-sm text-ink/70">Open an approved asset in <button type="button" onClick={() => navigate('campaign')} className="font-semibold text-accent-deep underline">Campaign</button> and choose <em>Send on WhatsApp</em>. Paste the numbers, and each chat opens in your own WhatsApp with the message ready.</p>
    {c.link_reachable === false && (
      <div role="alert" className="flex items-start gap-2 rounded-xl bg-warn/15 px-3 py-2 text-xs">
        <TriangleAlert size={14} className="mt-0.5 shrink-0" />
        <span>The tracked link in your messages points at this computer, so customers cannot open it. Set <code>PUBLIC_BASE_URL</code> in the server's .env to a public address (a tunnel such as Cloudflare Tunnel or ngrok) before you send.</span>
      </div>
    )}
  </Shell>
);

const FacebookCard = () => (
  <Shell icon={ThumbsUp} title="Facebook" status="Not connected" muted>
    <p className="text-sm text-ink/70">Pages and posts. Not built yet.</p>
    <button type="button" disabled className="btn-ghost h-9 w-fit px-3 text-sm opacity-60"><ThumbsUp size={14} /> Connect Facebook</button>
  </Shell>
);

// S23: link the accounts the campaigns go out on. Instagram and YouTube sign in through their own pages.
const Connections = ({ id: code }) => {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const reload = useCallback(
    () => api('/connections').then((d) => { setData(d); setError(''); }).catch((e) => setError(e.message)),
    []
  );
  useEffect(() => {
    reload();
  }, [reload]);

  const notice = code ? NOTICES[code] : null;
  const by = Object.fromEntries((data?.connections ?? []).map((c) => [c.provider, c]));

  return (
    <div className="flex flex-col gap-4">
      {notice && <p role="status" className={`rounded-2xl px-4 py-3 text-sm font-medium ${TONE[notice.tone]}`}>{notice.text}</p>}
      {error && <p role="alert" className="rounded-2xl bg-bad/15 px-4 py-3 text-sm">{error}</p>}
      {!data && !error && <OrbLoader kind="searching" label="Checking your accounts" className="rounded-2xl bg-white" />}
      {data && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2 [&>*]:min-w-0">
          <Instagram c={by.instagram} setup={data.setup} reload={reload} />
          <YouTube c={by.youtube} setup={data.setup} reload={reload} />
          <WhatsApp c={by.whatsapp} />
          <FacebookCard />
        </div>
      )}
      <p className="text-xs text-white/50">Logins are kept encrypted on this server and never shown. Disconnect removes them here; Instagram and Google also let you remove the app from their own settings.</p>
    </div>
  );
};

export default Connections;
