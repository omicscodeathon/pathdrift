import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface ProjectStore {
  currentProjectId: string | null
  currentAnalysisId: string | null
  currentDatasetId: string | null
  preprocessingJobId: string | null
  degResultId: string | null
  healthyNetworkId: string | null
  diseaseNetworkId: string | null
  humanDriftId: string | null
  mouseDriftId: string | null
  crossSpeciesId: string | null
  pathwayResultId: string | null
  setCurrentProject: (id: string | null) => void
  setCurrentAnalysis: (id: string | null) => void
  setCurrentDataset: (id: string | null) => void
  setWorkflowIds: (ids: Partial<Pick<ProjectStore, 'currentDatasetId' | 'preprocessingJobId' | 'degResultId' | 'healthyNetworkId' | 'diseaseNetworkId' | 'humanDriftId' | 'mouseDriftId' | 'crossSpeciesId' | 'pathwayResultId'>>) => void
}

export const useProjectStore = create<ProjectStore>()(
  persist(
    (set) => ({
      currentProjectId: null,
      currentAnalysisId: null,
      currentDatasetId: null,
      preprocessingJobId: null,
      degResultId: null,
      healthyNetworkId: null,
      diseaseNetworkId: null,
      humanDriftId: null,
      mouseDriftId: null,
      crossSpeciesId: null,
      pathwayResultId: null,
      setCurrentProject: (id) => set({
        currentProjectId: id,
        currentAnalysisId: null,
        currentDatasetId: null,
        preprocessingJobId: null,
        degResultId: null,
        healthyNetworkId: null,
        diseaseNetworkId: null,
        humanDriftId: null,
        mouseDriftId: null,
        crossSpeciesId: null,
        pathwayResultId: null,
      }),
      setCurrentAnalysis: (id) => set({ currentAnalysisId: id }),
      setCurrentDataset: (id) => set({ currentDatasetId: id }),
      setWorkflowIds: (ids) => set(ids),
    }),
    {
      name: 'pathdrift-project',
      partialize: (state) => ({
        currentProjectId: state.currentProjectId,
        currentAnalysisId: state.currentAnalysisId,
        currentDatasetId: state.currentDatasetId,
        preprocessingJobId: state.preprocessingJobId,
        degResultId: state.degResultId,
        healthyNetworkId: state.healthyNetworkId,
        diseaseNetworkId: state.diseaseNetworkId,
        humanDriftId: state.humanDriftId,
        mouseDriftId: state.mouseDriftId,
        crossSpeciesId: state.crossSpeciesId,
        pathwayResultId: state.pathwayResultId,
      }),
    }
  )
)
