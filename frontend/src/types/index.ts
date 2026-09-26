// Shared TypeScript types for PathDrift frontend

export type Species = 'human' | 'mouse'
export type DiseaseState = 'healthy' | 'early_cancer' | 'intermediate' | 'advanced' | 'cancer'
export type JobStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
export type DataType = 'raw_counts' | 'normalized' | 'microarray' | 'unknown'
export type NormMethod = 'log2cpm' | 'voom' | 'tpm' | 'fpkm' | 'deseq2_vst' | 'quantile' | 'none'
export type CorrelationMethod = 'pearson' | 'spearman' | 'partial'
export type MLModelType = 'logistic_regression' | 'random_forest' | 'svm' | 'gradient_boosting'
export type ExperimentType = 'expression_only' | 'drift_only' | 'combined'

export interface User {
  id: string
  email: string
  username: string
  full_name?: string
  institution?: string
  is_active: boolean
  created_at: string
}

export interface Project {
  id: string
  name: string
  description?: string
  research_question?: string
  is_public: boolean
  created_at: string
  updated_at: string
}

export interface Dataset {
  id: string
  project_id: string
  name: string
  description?: string
  species: Species
  tissue?: string
  source?: string
  accession?: string
  platform?: string
  data_type: DataType
  n_genes?: number
  n_samples?: number
  n_healthy?: number
  n_cancer?: number
  is_validated: boolean
  validation_errors?: Record<string, string[]>
  validation_warnings?: Record<string, string[]>
  created_at: string
}

export interface ValidationResult {
  dataset_id: string
  is_valid: boolean
  errors: string[]
  warnings: string[]
  summary: Record<string, unknown>
}

export interface Job {
  id: string
  analysis_id?: string
  celery_task_id?: string
  task_name: string
  status: JobStatus
  progress: number
  progress_message?: string
  error_message?: string
  started_at?: string
  completed_at?: string
  created_at: string
}

export interface Analysis {
  id: string
  project_id: string
  name: string
  description?: string
  status: JobStatus
  random_seed: number
  config_snapshot?: Record<string, unknown>
  software_versions?: Record<string, string>
  created_at: string
  updated_at: string
}

export interface GeneNetwork {
  id: string
  analysis_id: string
  name: string
  species: Species
  disease_state: DiseaseState
  correlation_method: CorrelationMethod
  correlation_threshold: number
  n_nodes?: number
  n_edges?: number
  density?: number
  avg_clustering_coefficient?: number
  avg_degree?: number
  status: JobStatus
  created_at: string
}

export interface DriftResult {
  id: string
  analysis_id: string
  healthy_network_id: string
  disease_network_id: string
  species: Species
  n_conserved_edges?: number
  n_gained_edges?: number
  n_lost_edges?: number
  global_drift_score?: number
  status: JobStatus
  created_at: string
}

export interface CrossSpeciesResult {
  id: string
  analysis_id: string
  human_drift_id: string
  mouse_drift_id: string
  n_orthologous_genes?: number
  n_conserved_drift?: number
  n_human_specific?: number
  n_mouse_specific?: number
  n_divergent?: number
  conservation_score?: number
  status: JobStatus
  created_at: string
}

export interface MLExperiment {
  id: string
  analysis_id: string
  name: string
  experiment_type: ExperimentType
  model_type: MLModelType
  random_seed: number
  cv_folds: number
  n_features_used?: number
  leakage_warnings?: string[]
  status: JobStatus
  created_at: string
}

export interface ModelMetric {
  id: string
  experiment_id: string
  split: string
  auroc?: number
  auprc?: number
  accuracy?: number
  sensitivity?: number
  specificity?: number
  precision?: number
  recall?: number
  f1?: number
  auroc_ci_lower?: number
  auroc_ci_upper?: number
  confusion_matrix?: { matrix: number[][] }
}

export interface PathwayResult {
  id: string
  analysis_id: string
  gene_set: string
  source: string
  species: Species
  n_significant?: number
  fdr_threshold: number
  status: JobStatus
  created_at: string
}

export interface NetworkNode {
  gene_id: string
  degree: number
  weighted_degree: number
  betweenness: number
  closeness: number
  clustering: number
  module?: string
}

export interface NetworkEdge {
  gene1: string
  gene2: string
  weight: number
  correlation: number
}

export interface NodeDrift {
  gene_id: string
  degree_healthy: number
  degree_disease: number
  degree_change: number
  betweenness_change: number
  closeness_change: number
  clustering_change: number
  node_drift_score: number
}

export interface CrossSpeciesGene {
  human_ensembl_id: string
  mouse_ensembl_id: string
  human_symbol?: string
  mouse_symbol?: string
  human_drift_score: number
  mouse_drift_score: number
  human_degree_change: number
  mouse_degree_change: number
  drift_classification: 'conserved' | 'human_specific' | 'mouse_specific' | 'divergent' | 'not_drifting'
}

export interface GeneLossNode {
  id: string
  label: string
  degree: number
}

export interface GeneLossEdge {
  source: string
  target: string
}

export interface GeneLossScore {
  risk_score: number
  probability: number
  predicted_loss: boolean
}

export interface GeneLossAnalysisResult {
  image_summary: {
    width: number
    height: number
    mean_intensity: number
    edge_density: number
  }
  network: {
    nodes: GeneLossNode[]
    edges: GeneLossEdge[]
  }
  gene_scores: Record<string, GeneLossScore>
  highest_risk_genes: Array<{
    gene: string
    risk_score: number
    probability: number
    predicted_loss: boolean
  }>
}
