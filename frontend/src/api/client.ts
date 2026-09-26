/**
 * PathDrift API Client
 * All backend communication goes through this module.
 * Uses axios with JWT authentication.
 */
import axios, { AxiosInstance, AxiosError } from 'axios'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

export const apiClient: AxiosInstance = axios.create({
  baseURL: `${BASE_URL}/api/v1`,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30_000,
})

// Attach JWT token to every request
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('pathdrift_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Handle 401 by clearing token
apiClient.interceptors.response.use(
  (res) => res,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('pathdrift_token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// ── Auth ──────────────────────────────────────────────────────────────────────

export const authApi = {
  login: (username: string, password: string) =>
    apiClient.post<{ access_token: string; token_type: string }>('/auth/login', { username, password }),
  register: (data: { email: string; username: string; password: string; full_name?: string; institution?: string }) =>
    apiClient.post('/auth/register', data),
  getMe: () => apiClient.get('/users/me'),
}

// ── Projects ──────────────────────────────────────────────────────────────────

export const projectApi = {
  list: () => apiClient.get('/projects/'),
  create: (data: { name: string; description?: string; research_question?: string; is_public?: boolean }) =>
    apiClient.post('/projects/', data),
}

export const analysisApi = {
  list: () => apiClient.get('/analyses/'),
  listForProject: (projectId: string) => apiClient.get(`/analyses/project/${projectId}`),
  create: (data: { project_id: string; name: string; description?: string; random_seed?: number }) =>
    apiClient.post('/analyses/', data),
  get: (id: string) => apiClient.get(`/analyses/${id}`),
}

// ── Datasets ──────────────────────────────────────────────────────────────────

export const datasetApi = {
  upload: (formData: FormData) =>
    apiClient.post('/datasets/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } }),
  list: (projectId: string) => apiClient.get(`/datasets/project/${projectId}`),
  get: (id: string) => apiClient.get(`/datasets/${id}`),
  validate: (id: string) => apiClient.post(`/datasets/${id}/validate`),
  getSamples: (id: string) => apiClient.get(`/datasets/${id}/samples`),
  delete: (id: string) => apiClient.delete(`/datasets/${id}`),
}

export const dataAcquisitionApi = {
  search: (params: { disease?: string; species?: string }) =>
    apiClient.get('/data-acquisition/search', { params }),
  select: (payload: { disease: string; species: string[]; selected_ids: string[]; analysis_type: string }) =>
    apiClient.post('/data-acquisition/select', payload),
  download: (payload: { project_id: string; selected_ids: string[]; disease: string }) =>
    apiClient.post('/data-acquisition/download', payload),
  getJob: (jobId: string) => apiClient.get(`/data-acquisition/jobs/${jobId}`),
  listDatasets: () => apiClient.get('/data-acquisition/datasets'),
}

// ── Import ────────────────────────────────────────────────────────────────────

export const importApi = {
  fromGEO: (data: { project_id: string; accession: string; species: string; tissue?: string }) =>
    apiClient.post('/import/geo', data),
  fromTCGA: (data: { project_id: string; project_code: string; tissue?: string }) =>
    apiClient.post('/import/tcga', data),
}

// ── Preprocessing ──────────────────────────────────────────────────────────────

export const preprocessingApi = {
  start: (config: object) => apiClient.post('/preprocessing/', config),
  get: (jobId: string) => apiClient.get(`/preprocessing/${jobId}`),
  getLatestForAnalysis: (analysisId: string) => apiClient.get(`/preprocessing/latest/analysis/${analysisId}`),
}

// ── DEG ───────────────────────────────────────────────────────────────────────

export const degApi = {
  run: (config: object) => apiClient.post('/deg/', config),
  get: (id: string) => apiClient.get(`/deg/${id}`),
  getLatestForAnalysis: (analysisId: string) => apiClient.get(`/deg/latest/analysis/${analysisId}`),
  getGenes: (id: string, significantOnly = true) =>
    apiClient.get(`/deg/${id}/genes`, { params: { significant_only: significantOnly } }),
  getLatestGenesForAnalysis: (analysisId: string, significantOnly = true) =>
    apiClient.get(`/deg/latest/analysis/${analysisId}/genes`, { params: { significant_only: significantOnly } }),
}

// ── Networks ──────────────────────────────────────────────────────────────────

export const networkApi = {
  build: (config: object) => apiClient.post('/networks/', config),
  get: (id: string) => apiClient.get(`/networks/${id}`),
  getEdges: (id: string, limit = 1000) => apiClient.get(`/networks/${id}/edges`, { params: { limit } }),
  getNodes: (id: string) => apiClient.get(`/networks/${id}/nodes`),
}

// ── Drift ─────────────────────────────────────────────────────────────────────

export const driftApi = {
  run: (config: object) => apiClient.post('/drift/', config),
  get: (id: string) => apiClient.get(`/drift/${id}`),
  getNodes: (id: string, limit = 500) => apiClient.get(`/drift/${id}/nodes`, { params: { limit } }),
  getEdges: (id: string, edgeType?: string) =>
    apiClient.get(`/drift/${id}/edges`, { params: { edge_type: edgeType } }),
}

// ── Cross-Species ──────────────────────────────────────────────────────────────

export const crossSpeciesApi = {
  run: (config: object) => apiClient.post('/cross-species/', config),
  get: (id: string) => apiClient.get(`/cross-species/${id}`),
  getGenes: (id: string, classification?: string) =>
    apiClient.get(`/cross-species/${id}/genes`, { params: { classification } }),
}

// ── ML ────────────────────────────────────────────────────────────────────────

export const mlApi = {
  createExperiment: (config: object) => apiClient.post('/ml/experiments', config),
  getExperiment: (id: string) => apiClient.get(`/ml/experiments/${id}`),
  getMetrics: (id: string) => apiClient.get(`/ml/experiments/${id}/metrics`),
  getFeatureImportances: (id: string) => apiClient.get(`/ml/experiments/${id}/feature-importances`),
}

// ── Gene Loss ───────────────────────────────────────────────────────────────

export const geneLossApi = {
  analyze: (payload: object) => apiClient.post('/gene-loss/analyze', payload),
}

// ── Validation ────────────────────────────────────────────────────────────────

export const validationApi = {
  compareModels: (expId: string) => apiClient.get(`/validation/experiments/${expId}/comparison`),
}

// ── Pathways ──────────────────────────────────────────────────────────────────

export const pathwayApi = {
  run: (config: object) => apiClient.post('/pathways/', config),
  get: (id: string) => apiClient.get(`/pathways/${id}`),
  getTerms: (id: string, significantOnly = true) =>
    apiClient.get(`/pathways/${id}/terms`, { params: { significant_only: significantOnly } }),
}

// ── Jobs ──────────────────────────────────────────────────────────────────────

export const jobsApi = {
  get: (id: string) => apiClient.get(`/jobs/${id}`),
  getForAnalysis: (analysisId: string) => apiClient.get(`/jobs/analysis/${analysisId}`),
  cancel: (id: string) => apiClient.post(`/jobs/${id}/cancel`),
}

// ── Orthology ──────────────────────────────────────────────────────────────────

export const orthologyApi = {
  stats: () => apiClient.get('/orthology/stats'),
  search: (params: { human_symbol?: string; mouse_symbol?: string }) =>
    apiClient.get('/orthology/search', { params }),
}

// ── Reports ────────────────────────────────────────────────────────────────────

export const reportsApi = {
  generate: (config: object) => apiClient.post('/reports/generate', config),
  downloadUrl: (analysisId: string, format = 'pdf') =>
    `${BASE_URL}/api/v1/reports/${analysisId}/download?format=${format}`,
}

// ── Health ─────────────────────────────────────────────────────────────────────

export const healthApi = {
  check: () => axios.get(`${BASE_URL}/api/health`),
}
