// The first-run walkthrough: whether this person has seen it on this device, and the language they took it in.
// The API keeps no account record, so "new account" means the first time this signed-in person (or the local
// user when login is off) opens the app on this device.
export const TOUR_EVENT = 'growit-tour-start';

const seenKey = (who) => `tour-seen:${who}`;
const LANG_KEY = 'tour-lang';

export const tourOwner = (user) => user?.sub || user?.email || 'local';

export const hasSeenTour = (who) => {
  try {
    return localStorage.getItem(seenKey(who)) === '1';
  } catch {
    return true; // storage blocked: do not show the tour on every load
  }
};

export const markTourSeen = (who) => {
  try {
    localStorage.setItem(seenKey(who), '1');
  } catch {
    // Storage blocked: the tour may show again next time.
  }
};

export const readTourLang = () => {
  try {
    return localStorage.getItem(LANG_KEY) || 'en';
  } catch {
    return 'en';
  }
};

export const saveTourLang = (lang) => {
  try {
    localStorage.setItem(LANG_KEY, lang);
  } catch {
    // Storage blocked: the choice holds for this visit.
  }
};

// Settings uses this to replay the walkthrough.
export const startTour = () => window.dispatchEvent(new Event(TOUR_EVENT));

// Where a sign-in lands. A first-timer goes to Home, where the walkthrough opens and explains each part (its last card
// already asks "start my first campaign" or "look around first"). Everyone who has seen it gets the entry chooser.
export const landingFor = (user) => (hasSeenTour(tourOwner(user)) ? 'start' : 'home');
