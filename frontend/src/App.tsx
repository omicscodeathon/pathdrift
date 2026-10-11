import { Routes, Route, Navigate } from 'react-router-dom'
import { ThemeProvider, createTheme, CssBaseline } from '@mui/material'
import { useAuthStore } from '@/store/authStore'
import Layout from '@/components/Layout'
import LoginPage from '@/pages/auth/LoginPage'
import RegisterPage from '@/pages/auth/RegisterPage'
import DashboardPage from '@/pages/DashboardPage'
import DatasetsPage from '@/pages/DatasetsPage'
import DataQualityPage from '@/pages/DataQualityPage'
import RunQCPage from '@/pages/RunQCPage'
import PreprocessingPage from '@/pages/PreprocessingPage'
import DEGPage from './pages/DEGPage'
import NetworksPage from '@/pages/NetworksPage'
import NetworkModulesPage from '@/pages/NetworkModulesPage'
import DriftPage from '@/pages/DriftPage'
import CrossSpeciesPage from '@/pages/CrossSpeciesPage'
import PredictionPage from '@/pages/PredictionPage'
import ValidationPage from '@/pages/ValidationPage'
import PathwaysPage from '@/pages/PathwaysPage'
import ReportsPage from '@/pages/ReportsPage'
import DataAcquisitionPage from './pages/DataAcquisitionPage'
import GeneLossPage from '@/pages/GeneLossPage'
import PPINetworkPage from '@/pages/PPINetworkPage'
import MorphologyPage from '@/pages/MorphologyPage'
import KeyDriftedPathwaysPage from '@/pages/KeyDriftedPathwaysPage'
import AnalysisRunPickerPage from '@/pages/AnalysisRunPickerPage'
import DifferentialExpressionPage from '@/pages/DifferentialExpressionPage'
import GeneNetworksPage from '@/pages/GeneNetworksPage'
import NetworkExplorerPage from '@/pages/NetworkExplorerPage'
import ModulesPage from '@/pages/ModulesPage'
import ModuleExplorerPage from '@/pages/ModuleExplorerPage'
import IntegratedAnalysisPage from '@/pages/IntegratedAnalysisPage'
import OrthologyPage from '@/pages/OrthologyPage'
import BiomarkersPage from '@/pages/BiomarkersPage'
import HubGenesPage from '@/pages/HubGenesPage'
import Phase6MLResultsPage from '@/pages/Phase6MLResultsPage'
import { useProjectStore } from '@/store/projectStore'

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

function ProjectNetworkExplorerRoute() {
  const currentRunId = useProjectStore((state) => state.currentRunId)
  return (
    <Navigate
      to={currentRunId ? `/runs/${currentRunId}/network-explorer` : '/analysis/select?page=network-explorer'}
      replace
    />
  )
}

function ProjectPpiRoute() {
  const currentRunId = useProjectStore((state) => state.currentRunId)
  return (
    <Navigate
      to={currentRunId ? `/runs/${currentRunId}/ppi-network` : '/analysis/select?page=ppi-network'}
      replace
    />
  )
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
          <Route path="data-quality" element={<DataQualityPage />} />
          <Route path="run-qc" element={<RunQCPage />} />
          <Route path="data-acquisition" element={<DataAcquisitionPage />} />
          <Route path="preprocessing" element={<PreprocessingPage />} />
          <Route path="deg" element={<DEGPage />} />
          <Route path="networks" element={<ProjectNetworkExplorerRoute />} />
          <Route path="network-builder" element={<NetworksPage />} />
          <Route path="network-modules" element={<NetworkModulesPage />} />
          <Route path="drift" element={<DriftPage />} />
          <Route path="cross-species" element={<CrossSpeciesPage />} />
          <Route path="prediction" element={<PredictionPage />} />
          <Route path="validation" element={<ValidationPage />} />
          <Route path="pathways" element={<PathwaysPage />} />
          <Route path="key-drifted-pathways" element={<KeyDriftedPathwaysPage />} />
          <Route path="reports" element={<ReportsPage />} />
          <Route path="gene-loss" element={<GeneLossPage />} />
          <Route path="ppi-network" element={<ProjectPpiRoute />} />
          <Route path="morphology" element={<MorphologyPage />} />
          <Route path="analysis/select" element={<AnalysisRunPickerPage />} />
          <Route path="runs/:runId/deg" element={<DifferentialExpressionPage />} />
          <Route path="runs/:runId/differential-expression" element={<DifferentialExpressionPage />} />
          <Route path="runs/:runId/networks" element={<GeneNetworksPage />} />
          <Route path="runs/:runId/network-explorer" element={<NetworkExplorerPage />} />
          <Route path="runs/:runId/ppi-network" element={<PPINetworkPage />} />
          <Route path="runs/:runId/modules" element={<ModulesPage />} />
          <Route path="runs/:runId/module-explorer" element={<ModuleExplorerPage />} />
          <Route path="runs/:runId/integrated-analysis" element={<IntegratedAnalysisPage />} />
          <Route path="runs/:runId/cross-species" element={<CrossSpeciesPage />} />
          <Route path="runs/:runId/orthology" element={<OrthologyPage />} />
          <Route path="runs/:runId/drift" element={<DriftPage />} />
          <Route path="runs/:runId/biomarkers" element={<BiomarkersPage />} />
          <Route path="runs/:runId/gene-loss" element={<GeneLossPage />} />
          <Route path="runs/:runId/hub-genes" element={<HubGenesPage />} />
          <Route path="runs/:runId/ml" element={<Phase6MLResultsPage />} />
          <Route path="runs/:runId/pathways" element={<PathwaysPage />} />
          <Route path="runs/:runId/key-drifted-pathways" element={<KeyDriftedPathwaysPage />} />
          <Route path="runs/:runId/morphology" element={<MorphologyPage />} />
        </Route>
      </Routes>
    </ThemeProvider>
  )
}
