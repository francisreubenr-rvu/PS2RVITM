import { useCallback, useEffect, useState } from 'react';
import Backdrop from './components/Backdrop.jsx';
import { MotionConfig, motion } from 'framer-motion';
import Navbar from './components/Navbar';
import Sidebar from './components/Sidebar';
import BottomNav from './components/BottomNav';
import RightPanel from './components/dashboard/RightPanel';
import Home from './pages/Home';
import Agent from './pages/Agent';
import Replies from './pages/Replies';
import Insights from './pages/Insights';
import Connections from './pages/Connections';
import Memory from './pages/Memory';
import Talk from './pages/Talk';
import Plan from './pages/Plan';
import Campaign from './pages/Campaign';
import Dashboard from './pages/Dashboard';
import BudgetPlanner from './pages/BudgetPlanner';
import ChangeLog from './pages/ChangeLog';
import Customers from './pages/Customers';
import BrandData from './pages/BrandData';
import Settings from './pages/Settings';
import Bakeoff from './pages/Bakeoff';
import Login from './pages/Login';
import Start from './pages/Start';
import Studio from './pages/Studio';
import Launch from './pages/Launch';
import Identity from './pages/Identity';
import Website from './pages/Website';
import Video from './pages/Video';
import { findPage, pages } from './navigation';
import { useRoute, navigate } from './lib/router';
import { useAuth } from './lib/auth';
import { landingFor } from './lib/tour';
import Walkthrough from './components/tour/Walkthrough';
import { TalkProvider } from './components/talk/TalkContext';
import AgnezDock from './components/talk/AgnezDock';
import Intro from './components/intro/Intro';
import { INTRO_START, markIntroSeen, setIntroActive, shouldPlayIntro } from './lib/intro';

const SCREENS = {
  start: Start,
  home: Home,
  agent: Agent,
  replies: Replies,
  insights: Insights,
  connections: Connections,
  memory: Memory,
  voice: Talk,
  plan: Plan,
  planner: BudgetPlanner,
  campaign: Campaign,
  dashboard: Dashboard,
  change: Talk,
  log: ChangeLog,
  customers: Customers,
  brand: BrandData,
  settings: Settings,
  bakeoff: Bakeoff,
  studio: Studio,
  launch: Launch,
  identity: Identity,
  website: Website,
  video: Video,
};

const readExpanded = () => {
  try {
    return localStorage.getItem('sidebar-expanded') === '1';
  } catch {
    return false;
  }
};

const AppInner = () => {
  const { me, loading, logout, signedIn } = useAuth();
  const { slug, param } = useRoute();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [expanded, setExpanded] = useState(readExpanded);

  useEffect(() => {
    try {
      localStorage.setItem('sidebar-expanded', expanded ? '1' : '0');
    } catch {
      // Storage blocked: the sidebar just starts collapsed next time.
    }
  }, [expanded]);

  // Links inside the summary drawer change the route; the drawer should not stay over the new page.
  useEffect(() => {
    setSummaryOpen(false);
  }, [slug, param]);

  useEffect(() => {
    // Signed-in people who land on #/login (a bookmark, a back button) go on: a first-timer to Home, where the
    // walkthrough opens, everyone else to the chooser.
    if (signedIn && slug === 'login') navigate(landingFor(me?.user));
  }, [signedIn, slug, me]);

  const closeSummary = useCallback(() => setSummaryOpen(false), []);

  const select = (next) => {
    if (next === 'logout') {
      logout().then(() => navigate('login'));
      return;
    }
    navigate(next);
  };

  if (loading) {
    return <Backdrop />;
  }

  // The local dummy sign-in (admin/admin) or the server session gates the app. Signed out shows the login.
  if (!signedIn) {
    return (
      <MotionConfig reducedMotion="user">
        <Login reason={slug === 'login' ? param : undefined} />
      </MotionConfig>
    );
  }

  // Signed in but still on #/login: wait for the redirect above instead of flashing the shell.
  if (slug === 'login') {
    return <Backdrop />;
  }

  const page = findPage(slug === 'change' ? 'voice' : slug) ?? pages.home;
  const Screen = SCREENS[page.slug];

  const onTalk = slug === 'voice' || slug === 'change';

  return (
    <MotionConfig reducedMotion="user">
      <TalkProvider user={me.user} sessionId={onTalk ? param : undefined} active={onTalk}>
      <Backdrop />
      <div className="flex min-h-dvh gap-4 p-3 sm:p-4 lg:h-dvh">
        <Sidebar
          active={page.slug}
          onSelect={select}
          expanded={expanded}
          onToggle={() => setExpanded((v) => !v)}
          mobileOpen={mobileOpen}
          onCloseMobile={() => setMobileOpen(false)}
          badges={{}}
        />

        <div className="glass-panel relative flex min-w-0 flex-1 flex-col rounded-[28px]">
          <main className="flex-1 overflow-y-auto p-4 pb-24 sm:p-6 sm:pb-24">
            <Navbar page={page} onSelect={select} onOpenMenu={() => setMobileOpen(true)} onOpenSummary={() => setSummaryOpen(true)} />
            <motion.div
              key={`${page.slug}/${param ?? ''}`}
              className="mt-6"
              initial={{ opacity: 0.35, y: 8 }}
              animate={{ opacity: 1, y: 0, transitionEnd: { transform: 'none' } }}
              transition={{ type: 'spring', stiffness: 260, damping: 28, mass: 0.9 }}
            >
              <Screen key={param} id={param} />
            </motion.div>
          </main>
          <BottomNav active={page.slug} onSelect={select} />
        </div>

        <RightPanel drawerOpen={summaryOpen} onCloseDrawer={closeSummary} />
      </div>
      {/* The guided tour waits until the entry chooser is done, so it never moves the page mid-decision. */}
      {slug !== 'start' && !onTalk && <AgnezDock hideIdle={slug === 'home'} />}
      {slug !== 'start' && <Walkthrough user={me.user} />}
      </TalkProvider>
    </MotionConfig>
  );
};

// The opening animation plays when the site is opened. The page loads behind it, so when it clears the login screen (or the app) is there.
const App = () => {
  const [intro, setIntro] = useState(() => {
    const play = shouldPlayIntro();
    setIntroActive(play);
    return play;
  });
  useEffect(() => {
    const again = () => { setIntroActive(true); setIntro(true); };
    window.addEventListener(INTRO_START, again);
    return () => window.removeEventListener(INTRO_START, again);
  }, []);
  return (
    <>
      <AppInner />
      {intro && <Intro onDone={() => { markIntroSeen(); setIntro(false); setIntroActive(false); }} />}
    </>
  );
};

export default App;
