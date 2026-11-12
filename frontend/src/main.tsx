/// <reference types="vite/client" />
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import '@fontsource/be-vietnam-pro/400.css';
import '@fontsource/be-vietnam-pro/500.css';
import '@fontsource/be-vietnam-pro/600.css';
import '@fontsource/be-vietnam-pro/700.css';
import './fonts.css';
import './styles.css';

const mounted = globalThis as typeof globalThis & { __nomReactRoot?: ReactDOM.Root };
mounted.__nomReactRoot?.unmount();
const previousHost = document.getElementById('root')!;
const host = document.createElement('div');
host.id = 'root';
previousHost.replaceWith(host);
const root = ReactDOM.createRoot(host);
mounted.__nomReactRoot = root;
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
import.meta.hot?.dispose(() => {
  root.unmount();
  if (mounted.__nomReactRoot === root) delete mounted.__nomReactRoot;
});
