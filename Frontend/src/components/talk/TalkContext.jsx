import { createContext, useContext } from 'react';
import { useTalk } from './useTalk';

// The conversation with Agnez belongs to the app, not to one screen: it keeps going, with its messages, its interview and its live
// call, while the person moves between pages. The Talk screen and the floating dock both read it from here.
const Ctx = createContext(null);

export function TalkProvider({ user, sessionId, active, children }) {
  const talk = useTalk({ sessionId, user, active });
  return <Ctx.Provider value={talk}>{children}</Ctx.Provider>;
}

export function useTalkContext() {
  const v = useContext(Ctx);
  if (!v) throw new Error('useTalkContext must be used inside <TalkProvider>');
  return v;
}
