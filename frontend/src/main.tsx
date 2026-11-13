/** Load local Public Sans fonts and render the independent client. */
import React from 'react';
import ReactDOM from 'react-dom/client';
import '@fontsource/public-sans/400.css';
import '@fontsource/public-sans/600.css';
import '@fontsource/public-sans/700.css';
import './styles/tokens.css';
import './styles/global.css';
import App from './App';
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
