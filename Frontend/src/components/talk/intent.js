// What a person means by what they said to Talk. Plain rules, no model: instant, free, and the same answer every time.
// It reads English, with the common Hindi and Kannada words for the same things. Anything it cannot place is "unknown", and Talk
// then says what it can do instead of guessing. A change is never made from this alone: Talk always shows what it touches first.

export const normalize = (text) =>
  String(text || '')
    .toLowerCase()
    .normalize('NFC')
    .replace(/[^\p{L}\p{M}\p{N}\s]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();

const has = (t, words) => words.some((w) => (w.includes(' ') ? ` ${t} `.includes(` ${w} `) : t.split(' ').includes(w) || (!/^[a-z]+$/.test(w) && t.includes(w))));

const YES = ['yes', 'yeah', 'yep', 'sure', 'ok', 'okay', 'apply', 'confirm', 'go ahead', 'do it', 'correct', 'right', 'proceed', 'haan', 'han', 'ji', 'theek hai', 'हाँ', 'हां', 'जी', 'ठीक है', 'हौदु', 'houdu', 'ಹೌದು', 'ಸರಿ', 'sari'];
const NO = ['no', 'nope', 'cancel', 'discard', 'stop', 'dont', 'don t', 'do not', 'never mind', 'nevermind', 'nahi', 'nahin', 'mat', 'नहीं', 'नही', 'रहने दो', 'illa', 'beda', 'ಇಲ್ಲ', 'ಬೇಡ'];
const REPEAT = ['can you repeat that for me', 'can you repeat that', 'could you repeat that', 'repeat', 'repeat that', 'say that again', 'say it again', 'read it again', 'pardon', 'come again', 'dobara', 'phir se', 'दोबारा', 'फिर से', 'matte helu', 'ಮತ್ತೆ ಹೇಳಿ'];
const HELP = ['help', 'help me', 'what can you do', 'what can i say', 'madad', 'मदद', 'sahaya', 'ಸಹಾಯ'];
const SKIP = ['skip', 'skip it', 'skip this', 'skip this one', 'chhod do', 'छोड़ दो', 'bidi', 'ಬಿಡಿ'];
const FINISH = ['build the plan', 'build my plan', 'make the plan', 'create the plan', 'plan banao', 'प्लान बनाओ', 'yojane maadi', 'ಯೋಜನೆ ಮಾಡಿ'];
const NEW = ['new campaign', 'start a campaign', 'start campaign', 'create a campaign', 'new offer', 'new post', 'start over', 'naya campaign', 'नया कैंपेन', 'नया ऑफर', 'नया प्रचार', 'ಹೊಸ ಪ್ರಚಾರ', 'ಹೊಸ ಆಫರ್', 'hosa prachara'];
const CHANGE = ['change', 'update', 'edit', 'replace', 'make it', 'set', 'increase', 'decrease', 'reduce', 'raise', 'lower', 'rename', 'move', 'postpone', 'badlo', 'badal', 'बदलो', 'बदल', 'बदलें', 'ಬದಲಿಸಿ', 'ಬದಲಾಯಿಸಿ', 'ಬದಲು'];
const OPEN = ['open', 'go to', 'goto', 'show', 'show me', 'take me to', 'take me', 'switch to', 'navigate to', 'kholo', 'खोलो', 'dikhao', 'दिखाओ', 'tereyiri', 'ತೆರೆಯಿರಿ', 'ತೋರಿಸಿ'];

// slug, then the words that name that screen.
const PAGES = [
  ['customers', ['customers', 'customer', 'customer list', 'contacts', 'people', 'ग्राहक', 'ಗ್ರಾಹಕ', 'ಗ್ರಾಹಕರು']],
  ['connections', ['connections', 'connection', 'connect', 'instagram', 'youtube']],
  ['memory', ['memory', 'remember', 'मेमोरी', 'ಮೆಮೊರಿ']],
  ['settings', ['settings', 'setting', 'preferences', 'सेटिंग', 'सेटिंग्स', 'ಸೆಟ್ಟಿಂಗ್', 'ಸೆಟ್ಟಿಂಗ್ಸ್']],
  ['insights', ['insights', 'insight', 'analytics', 'graphs', 'results', 'reports']],
  ['dashboard', ['dashboard', 'डैशबोर्ड', 'ಡ್ಯಾಶ್‌ಬೋರ್ಡ್']],
  ['plan', ['plan', 'प्लान', 'ಯೋಜನೆ']],
  ['campaign', ['campaign', 'campaigns', 'posts', 'कैंपेन', 'ಪ್ರಚಾರ']],
  ['website', ['website', 'site', 'web page']],
  ['identity', ['identity', 'logo', 'colours', 'colors', 'brand look', 'names and brand']],
  ['brand', ['brand and data', 'shop details', 'menu', 'prices list', 'business details']],
  ['video', ['video', 'videos', 'reels', 'reel']],
  ['studio', ['studio']],
  ['agent', ['agent', 'autopilot', 'auto pilot']],
  ['replies', ['replies', 'inquiries', 'enquiries', 'messages from customers']],
  ['planner', ['planner', 'budget', 'budget planner']],
  ['log', ['log', 'history', 'change log']],
  ['launch', ['build my business', 'launch', 'new business', 'start a business']],
  ['home', ['home', 'home screen', 'main screen', 'start page']],
];
export const PAGE_NAMES = Object.fromEntries([
  ['customers', 'Customers'], ['connections', 'Connections'], ['memory', 'Memory'], ['settings', 'Settings'], ['insights', 'Insights'], ['dashboard', 'Dashboard'],
  ['plan', 'Plan'], ['campaign', 'Campaign'], ['website', 'Website'], ['identity', 'Names and brand look'], ['brand', 'Brand and data'], ['video', 'Reels'], ['studio', 'Studio'],
  ['agent', 'Agent'], ['replies', 'Replies'], ['planner', 'Budget planner'], ['log', 'Change log'], ['launch', 'Build my business'], ['home', 'Home'],
]);

const pageIn = (t) => PAGES.find(([, words]) => has(t, words))?.[0] ?? null;

// state: 'home' (nothing under way), 'interview' (answering questions), 'confirm' (a change is waiting for a yes or no)
export function understand(text, state = 'home') {
  const t = normalize(text);
  if (!t) return { intent: 'empty' };
  const short = t.split(' ').length <= 4;

  if (state === 'confirm') {
    if (has(t, NO)) return { intent: 'no' };
    if (has(t, YES)) return { intent: 'yes' };
    if (has(t, REPEAT)) return { intent: 'repeat' };
    return { intent: 'unknown' };
  }

  const whole = (list) => list.includes(t);

  if (state === 'interview') {
    // Anything that is not exactly a command is the answer to the question being asked: "Next Level Cafe" is a business name.
    if (whole(REPEAT)) return { intent: 'repeat' };
    if (whole(HELP)) return { intent: 'help' };
    if (whole(FINISH)) return { intent: 'finish' };
    if (whole(SKIP)) return { intent: 'skip' };
    if (whole(NEW)) return { intent: 'new_campaign' };
    const opens = OPEN.some((w) => t.startsWith(`${w} `));
    const page = opens && short ? pageIn(t) : null;
    if (page) return { intent: 'navigate', slug: page };
    return { intent: 'answer' };
  }

  if (whole(REPEAT) || (has(t, REPEAT) && short)) return { intent: 'repeat' };
  if (has(t, HELP) && short) return { intent: 'help' };

  if (has(t, NEW)) return { intent: 'new_campaign' };
  if (has(t, OPEN)) {
    const page = pageIn(t);
    if (page) return { intent: 'navigate', slug: page };
  }
  if (has(t, CHANGE)) return { intent: 'change', text };
  if (short) {
    const page = pageIn(t);
    if (page) return { intent: 'navigate', slug: page };
  }
  return { intent: 'unknown' };
}

// A question put to the assistant, as opposed to an answer to the interview. "What a Cake" is a business name; "what does that mean" is a
// question. So a question needs a question mark, or a question word followed by enough words to be a sentence.
const QUESTION_START = /^(what|why|how|when|where|who|which|can|could|should|would|is|are|do|does|did|will|tell me|explain|help me|kya|kyun|kaise|क्या|क्यों|कैसे|कब|कहाँ|ಏನು|ಯಾಕೆ|ಹೇಗೆ|ಯಾವಾಗ)(?=\s|$)/u;
export const looksLikeQuestion = (text) => {
  const raw = String(text || '').trim();
  if (/[?？]\s*$/.test(raw)) return true;
  const t = normalize(raw);
  return t.split(' ').length >= 4 && QUESTION_START.test(t);
};
