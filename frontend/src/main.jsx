import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { CssBaseline, ThemeProvider, createTheme } from '@mui/material'
import './index.css'
import App from './App.jsx'
import { CurrentUserProvider } from './context/CurrentUserContext.jsx'

// Set up once, here, so every later page inherits it rather than each
// wiring its own styling from scratch.
const theme = createTheme();

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <CurrentUserProvider>
        <App />
      </CurrentUserProvider>
    </ThemeProvider>
  </StrictMode>,
)
