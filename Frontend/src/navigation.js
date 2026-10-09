import { NO_BACKEND } from './data/studio';
import {
  House,
  Mic,
  ShieldCheck,
  Scale,
  LayoutGrid,
  FileText,
  ChartNoAxesColumn,
  Bot,
  MessageCircleReply,
  History,
  Users,
  Store,
  Settings,
  FlaskConical,
  LogOut,
  Sparkles,
  Rocket,
  Palette,
  Globe,
  Clapperboard,
  Wrench,
  Hourglass,
  Brain,
  Compass,
  Megaphone,
  ChartSpline,
  Plug,
} from 'lucide-react';

// Screens from docs/screen-flow.md. `slug` is the URL hash (#/board).
export const pages = {
  // S0b: the post-login chooser. Reachable at #/start; not in the rail, it is the landing right after sign-in.
  start: { slug: 'start', screen: 'S0b', label: 'Get started', icon: Compass, description: 'Choose where to begin.' },
  home: { slug: 'home', screen: 'S2', label: 'Home', icon: House, description: 'Your campaign at a glance.' },
  insights: { slug: 'insights', screen: 'S22', label: 'Insights', icon: ChartSpline, description: 'How campaigns turned out. Sample data for now.' },
  memory: { slug: 'memory', screen: 'S24', label: 'Memory', icon: Brain, description: 'What GrowIt knows about your business. Edit anything.' },
  connections: { slug: 'connections', screen: 'S23', label: 'Connections', icon: Plug, description: 'Link Instagram and YouTube. See how WhatsApp sends.' },
  replies: { slug: 'replies', screen: 'S21', label: 'Replies', icon: MessageCircleReply, description: 'Answers customer messages from your locked facts only.' },
  agent: { slug: 'agent', screen: 'S20', label: 'Agent', icon: Bot, description: 'Describe your idea once. The agent plans the work.' },
  voice: { slug: 'voice', screen: 'S3', label: 'Talk', icon: Mic, description: 'Talk to Agnez. Every answer is kept in your own words.' },
  plan: { slug: 'plan', screen: 'S4', label: 'Plan', icon: ShieldCheck, description: 'What you said, as a plan.' },
  campaign: { slug: 'campaign', screen: 'S7', label: 'Campaign', icon: LayoutGrid, description: 'Every asset, with its fact and meaning checks.' },
  dashboard: { slug: 'dashboard', screen: 'S9', label: 'Dashboard', icon: ChartNoAxesColumn, description: 'Sends, clicks and checks, from this app only.' },
  planner: { slug: 'planner', screen: 'S5', label: 'Budget Planner', icon: Scale, description: 'See what fits your time, money and review effort.' },
  log: { slug: 'log', screen: 'S11', label: 'Change Log', icon: History, description: 'What changed, who changed it and why.' },
  customers: { slug: 'customers', screen: 'S12', label: 'Customers', icon: Users, description: 'Your people and who agreed to hear from you.' },
  brand: { slug: 'brand', screen: 'S1', label: 'Brand & Data', icon: Store, description: 'Menu, photos, posts and brand rules, set once.' },
  settings: { slug: 'settings', screen: 'S13', label: 'Settings', icon: Settings, description: 'Keys, voice, planner numbers and guardrails.' },
  studio: { slug: 'studio', screen: 'S15', label: 'Studio', icon: Sparkles, description: 'Pick what you want made.' },
  launch: { slug: 'launch', screen: 'S16', label: 'Build my business', icon: Rocket, description: 'No business yet? Get ideas, a name and a launch pack.' },
  identity: { slug: 'identity', screen: 'S17', label: 'Names & Brand look', icon: Palette, description: 'Names, taglines, colours and starter logos.' },
  website: { slug: 'website', screen: 'S18', label: 'Website', icon: Globe, description: 'A one-page site from your menu and offer.' },
  video: { slug: 'video', screen: 'S19', label: 'Reels & Video', icon: Clapperboard, description: 'Plan a short promo reel.' },
  bakeoff: { slug: 'bakeoff', screen: 'S14', label: 'Bake-off', icon: FlaskConical, description: 'Team tool: score voices per language.' },
};

// The rail shows Home, then a few groups the owner can fold away. A group holding the page you are on always opens.
// Brand and site screens sit together, folded by default. The bake-off is a team tool: it stays reachable at #/bakeoff but is not in the rail.
// Settings and Log out sit in the footer.
export const homeItem = pages.home;
export const sidebarGroups = [
  { id: 'start', title: 'Start', icon: Compass, defaultOpen: true, items: [pages.agent, pages.voice, pages.launch] },
  { id: 'campaign', title: 'Campaign', icon: Megaphone, defaultOpen: true, items: [pages.campaign, pages.plan, pages.dashboard, pages.insights] },
  { id: 'tools', title: 'Tools', icon: Wrench, defaultOpen: false, items: [pages.planner, pages.replies, pages.log] },
  { id: 'brand', title: 'Brand and site', icon: Palette, defaultOpen: false, items: [pages.studio, pages.brand, pages.identity, pages.website, pages.video] },
];

export const groupOf = (slug) => sidebarGroups.find((g) => g.items.some((i) => i.slug === slug))?.id;

export const settingsItem = pages.settings;
export const connectionsItem = pages.connections;
export const customersItem = pages.customers;
export const memoryItem = pages.memory;

export const logoutItem = { slug: 'logout', label: 'Log out', icon: LogOut };

// Bottom pill: the main flow in order (docs/screen-flow.md section 2).
export const flowSteps = [
  { slug: 'voice', label: 'Talk', icon: Mic },
  { slug: 'plan', label: 'Plan', icon: ShieldCheck },
  { slug: 'campaign', label: 'Campaign', icon: LayoutGrid },
  { slug: 'dashboard', label: 'Dashboard', icon: ChartNoAxesColumn },
];

export const findPage = (slug) => pages[slug];

export const hasBackend = (slug) => !NO_BACKEND.includes(slug);
