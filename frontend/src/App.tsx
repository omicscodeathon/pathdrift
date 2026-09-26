import { Routes, Route, Navigate } from 'react-router-dom'
import { ThemeProvider, createTheme, CssBaseline } from '@mui/material'
import { useAuthStore } from '@/store/authStore'
import Layout from '@/components/Layout'
import LoginPage from '@/pages/auth/LoginPage'
import RegisterPage from '@/pages/auth/RegisterPage'
import DashboardPage from '@/pages/DashboardPage'
import DatasetsPage from '@/pages/DatasetsPage'
import PreprocessingPage from '@/pages/PreprocessingPage'
import DEGPage from '@/pages/DEGPage'
import NetworksPage from '@/pages/NetworksPage'
import DriftPage from '@/pages/DriftPage'
import CrossSpeciesPage from '@/pages/CrossSpeciesPage'
import PredictionPage from '@/pages/PredictionPage'
import ValidationPage from '@/pages/ValidationPage'
import PathwaysPage from '@/pages/PathwaysPage'
import ReportsPage from '@/pages/ReportsPage'
import DataAcquisitionPage from '@/pages/DataAcquisitionPage'
import GeneLossPage from '@/pages/GeneLossPage'

const theme = createTheme({
  palette: {
    mode: 'light',
    primary: {
      main: '#1565c0',
      dark: '#0d47a1',
      light: '#1976d2',
    },
    secondary: {
      main: '#00acc1',
    },
    background: {
      default: '#f8fafc',
      paper: '#ffffff',
    },
    text: {
      primary: '#1a1a2e',
      secondary: '#64748b',
    },
  },
  typography: {
    fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    h1: { fontWeight: 700 },
    h2: { fontWeight: 700 },
    h3: { fontWeight: 600 },
    h4: { fontWeight: 600 },
    h5: { fontWeight: 600 },
    h6: { fontWeight: 600 },
  },
  shape: {
    borderRadius: 8,
  },
  components: {
    MuiButton: {
      styleOverrides: {
        root: { textTransform: 'none', fontWeight: 500 },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: { backgroundImage: 'none' },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { fontWeight: 500 },
      },
    },
  },
})

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { token } = useAuthStore()
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<DashboardPage />} />
          <Route path="datasets" element={<DatasetsPage />} />
          <Route path="data-acquisition" element={<DataAcquisitionPage />} />
          <Route path="preprocessing" element={<PreprocessingPage />} />
          <Route path="deg" element={<DEGPage />} />
          <Route path="networks" element={<NetworksPage />} />
          <Route path="drift" element={<DriftPage />} />
          <Route path="cross-species" element={<CrossSpeciesPage />} />
          <Route path="prediction" element={<PredictionPage />} />
          <Route path="validation" element={<ValidationPage />} />
          <Route path="pathways" element={<PathwaysPage />} />
          <Route path="reports" element={<ReportsPage />} />
          <Route path="gene-loss" element={<GeneLossPage />} />
        </Route>
      </Routes>
    </ThemeProvider>
  )
}
