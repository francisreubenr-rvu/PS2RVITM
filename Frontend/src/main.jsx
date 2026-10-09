import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import './campaign/campaign.css';
import './campaign/theme.css';
import App from './App.jsx';
import { AgnezProvider } from './voice/agnez';
import { StoreProvider } from './state/store';
import { AuthProvider } from './lib/auth';
import { applyAppearance, readAppearance } from './lib/appearance';

// Before the first render, so the saved accent and surface never flash in after the default ones.
applyAppearance(readAppearance());

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <AuthProvider>
      <StoreProvider>
        <AgnezProvider><App /></AgnezProvider>
      </StoreProvider>
    </AuthProvider>
  </StrictMode>
);
