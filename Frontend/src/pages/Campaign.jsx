import { useEffect, useState } from 'react';
import { CampaignView } from '../campaign/components/campaign';
import { Button, Empty, ErrorNote } from '../campaign/components/ui';
import { listOverview } from '../campaign/lib/api';
import { humanize } from '../campaign/lib/format';
import { go, setCurrent } from '../campaign/lib/current';
import { navigate } from '../lib/router';
import { OrbLoader } from '../orb/orbPresence';

const nameOf = (b) => (!b ? '' : typeof b === 'string' ? b : b.name || '');

// One row per campaign, from the API's own overview: id, business name, status and real totals.
const toRow = (r) => ({ id: r.campaign_id, name: nameOf(r.business), status: r.status, totals: r.totals || {} });

// S7: the Campaign tab. Open it and every campaign is here; open one to work on it.
function CampaignList() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    listOverview()
      .then((res) => {
        if (!live) return;
        setRows(
          Array.isArray(res)
            ? res.map(toRow)
            : res.legacy.map((c) => ({ id: c.id, name: c.transcript.slice(0, 48), status: c.status, totals: {} })),
        );
      })
      .catch((e) => {
        if (!live) return;
        setError(e.message);
        setRows([]);
      });
    return () => {
      live = false;
    };
  }, []);

  // Opening a campaign makes it the current one and takes the board route.
  const open = (c) => {
    setCurrent({ id: c.id, business: c.name });
    go({ name: 'campaign', id: c.id });
  };

  const count = rows?.length ?? 0;

  return (
    <div className="page">
      <header className="camp-head">
        <div>
          <p className="kicker">Campaigns</p>
          <h1 className="display-sm">{count ? `${count} ${count === 1 ? 'campaign' : 'campaigns'}` : 'Your campaigns'}</h1>
          <p className="muted small">Everything you have made. Open one to see its posts, posters and messages, each checked against your locked facts.</p>
        </div>
        {count ? (
          <div className="camp-actions">
            <Button onClick={() => navigate('voice')}>New campaign</Button>
          </div>
        ) : null}
      </header>

      {error ? <ErrorNote>{error}</ErrorNote> : null}
      {rows === null && !error ? <OrbLoader kind="loading" label="Loading campaigns" className="rounded-2xl bg-white" /> : null}

      {rows?.length === 0 && !error ? (
        <div style={{ display: 'grid', gap: 'var(--s4)' }}>
          <Empty title="No campaigns yet">Answer a few questions first. Your campaign appears here once the conversation is finished.</Empty>
          <div>
            <Button variant="primary" onClick={() => navigate('voice')}>Start talking</Button>
          </div>
        </div>
      ) : null}

      {count ? (
        <ul className="campaign-list">
          {rows.map((c) => {
            const t = c.totals || {};
            return (
              <li key={c.id}>
                <button type="button" className="campaign-row" onClick={() => open(c)}>
                  <span className="campaign-name">{c.name || `Campaign ${c.id.slice(0, 6)}`}</span>
                  <span className="badge badge-neutral">{humanize(c.status)}</span>
                  <span className="campaign-stats">{t.assets ?? 0} assets, {t.approved ?? 0} approved, {t.clicks ?? 0} clicks</span>
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

// The board for one campaign. Kept at #/campaign/<id> exactly as it worked before, with one way back to the list.
function CampaignBoard({ id }) {
  return (
    <>
      <div className="cv-bar">
        <Button variant="quiet" onClick={() => navigate('campaign')}>All campaigns</Button>
      </div>
      <CampaignView key={id} id={id} go={go} onBusiness={(business) => setCurrent({ business })} />
    </>
  );
}

const Campaign = ({ id }) => (
  <div className="cv">{id ? <CampaignBoard id={id} /> : <CampaignList />}</div>
);

export default Campaign;
