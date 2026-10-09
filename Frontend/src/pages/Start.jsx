import { useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Compass, Megaphone, Rocket } from 'lucide-react';
import { navigate } from '../lib/router';
import { useCurrent } from '../campaign/lib/current';

// One option: an icon, a plain title and a one-line hint. The primary carries the accent; the other sits low-contrast.
const Choice = ({ icon: Icon, title, hint, onClick, primary = false }) => (
  <button
    type="button"
    onClick={onClick}
    className={`flex w-full items-start gap-4 rounded-2xl p-4 text-left transition-colors ${
      primary ? 'bg-accent text-on-accent hover:bg-accent-hover' : 'bg-ink/5 text-ink hover:bg-ink/10'
    }`}
  >
    <span className={`grid size-11 shrink-0 place-items-center rounded-xl ${primary ? 'bg-ink/10' : 'bg-accent-soft text-accent-deep'}`}>
      <Icon size={22} />
    </span>
    <span className="min-w-0">
      <span className="block font-semibold">{title}</span>
      <span className={`mt-0.5 block text-sm ${primary ? 'opacity-75' : 'text-ink/60'}`}>{hint}</span>
    </span>
  </button>
);

const swap = {
  initial: { opacity: 0, y: 10, filter: 'blur(6px)' },
  animate: { opacity: 1, y: 0, filter: 'blur(0px)' },
  exit: { opacity: 0, y: -8, filter: 'blur(6px)' },
  transition: { duration: 0.22, ease: [0.4, 0, 0.2, 1] },
};

// S0b: the first decision after sign-in. One question at a time, so the next step is never in doubt.
const Start = () => {
  const [step, setStep] = useState('campaign'); // 'campaign' first, then 'intent' when there is no active campaign
  const cur = useCurrent();

  // This chooser is for people who have already seen the walkthrough (a first sign-in goes to Home, where the tour
  // opens). It must not mark the tour as seen: a first-timer who reaches it by a bookmark still gets the tour on Home.

  // They have a campaign: open its dashboard (the current campaign from lib/current.js when it is known).
  // Otherwise the bare dashboard route, which shows the empty state to start one.
  const openDashboard = () => {
    if (cur.id) navigate('dashboard', cur.id);
    else navigate('dashboard');
  };

  const go = (slug) => navigate(slug);

  return (
    <div className="mx-auto flex min-h-[24rem] w-full max-w-lg flex-col justify-center pt-2 sm:pt-8">
      <AnimatePresence mode="wait" initial={false}>
        {step === 'campaign' ? (
          <motion.section key="campaign" {...swap} className="card">
            <p className="text-xs font-semibold uppercase tracking-wide text-accent-deep">Welcome</p>
            <h1 className="mt-1.5 text-2xl font-bold tracking-tight sm:text-3xl">Do you have an active campaign?</h1>
            <p className="mt-2 text-sm text-ink/60">Pick one and we open the right screen. You can change your mind any time.</p>
            <div className="mt-5 flex flex-col gap-3">
              <Choice
                icon={Megaphone}
                title="Yes, it is running"
                hint="Open the dashboard: activity, insights, customers reached and outreach."
                onClick={openDashboard}
                primary
              />
              <Choice icon={Compass} title="Not yet" hint="I am planning my first campaign." onClick={() => setStep('intent')} />
            </div>
          </motion.section>
        ) : (
          <motion.section key="intent" {...swap} className="card">
            <p className="text-xs font-semibold uppercase tracking-wide text-accent-deep">Start a campaign</p>
            <h1 className="mt-1.5 text-2xl font-bold tracking-tight sm:text-3xl">What would you like to do?</h1>
            <p className="mt-2 text-sm text-ink/60">Tell us the offer by voice and GrowIt writes the campaign with you.</p>
            <div className="mt-5 flex flex-col gap-3">
              <Choice
                icon={Rocket}
                title="Start a campaign"
                hint="Ideate over voice. Answer a few questions and we build the plan."
                onClick={() => go('voice')}
                primary
              />
              <Choice icon={Compass} title="Just looking around" hint="Go to the app and explore on your own." onClick={() => go('home')} />
            </div>
            <button type="button" onClick={() => setStep('campaign')} className="mt-4 text-sm font-medium text-ink/55 hover:text-ink">
              Back
            </button>
          </motion.section>
        )}
      </AnimatePresence>
    </div>
  );
};

export default Start;
