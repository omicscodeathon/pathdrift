import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { phase3Api, phase4Api, phase5Api, phase6Api } from '@/api/client'
import { useProjectStore } from '@/store/projectStore'
import {
  fetchAllDeg,
  NETWORK_EDGE_LIMIT,
  NETWORK_NODE_LIMIT,
  PAGE_SIZE,
  type Network,
  type Summary,
} from '@/pages/analysis/shared'

const RESULT_STALE_TIME = 5 * 60_000
type ResultPage = { total: number; items: unknown[] }

export default function RunResultsPrefetcher() {
  const runId = useProjectStore((state) => state.currentRunId)
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!runId) return
    let cancelled = false

    const warm = async <T,>(queryKey: readonly unknown[], queryFn: () => Promise<T>) => {
      if (cancelled) return
      try {
        await queryClient.prefetchQuery({ queryKey, queryFn, staleTime: RESULT_STALE_TIME })
      } catch (error) {
        console.warn(`Could not preload saved result for run ${runId}`, queryKey, error)
      }
    }

    const warmPaged = async (
      queryKey: (page: number) => readonly unknown[],
      queryPage: (page: number) => Promise<ResultPage>,
      pageSize = PAGE_SIZE,
    ) => {
      const firstKey = queryKey(0)
      await warm(firstKey, () => queryPage(0))
      const firstPage = queryClient.getQueryData<ResultPage>(firstKey)
      const pageCount = Math.ceil((firstPage?.total ?? 0) / pageSize)
      for (let start = 1; start < pageCount && !cancelled; start += 4) {
        const pages = Array.from({ length: Math.min(4, pageCount - start) }, (_, index) => start + index)
        await Promise.allSettled(pages.map((page) => warm(queryKey(page), () => queryPage(page))))
      }
    }

    const preload = async () => {
      await warm(['run-artifacts', runId], () =>
        phase3Api.artifacts(runId).then((response) => response.data as { items: Array<{ path: string }> }),
      )
      if (cancelled) return
      const artifactPaths = queryClient.getQueryData<{ items: Array<{ path: string }> }>(['run-artifacts', runId])?.items
        .map((artifact) => artifact.path) ?? []
      const hasArtifact = (prefix: string) => artifactPaths.some((path) => path.startsWith(prefix))

      const baseQueries: Array<Promise<void>> = [
        warm(['phase3-summary', runId], () => phase3Api.summary(runId).then((response) => response.data as Summary)),
        warm(['phase3-datasets', runId], () => phase3Api.datasets(runId).then((response) => response.data)),
        warm(['phase3-networks', runId], () => phase3Api.networks(runId).then((response) => (response.data as { items: Network[] }).items)),
        warm(['phase3-modules', runId], () => phase3Api.modules(runId, { limit: 500, offset: 0 }).then((response) => response.data)),
      ]
      if (hasArtifact('orthology/')) {
        baseQueries.push(warm(['phase4-orthology-summary', runId], () => phase4Api.orthologySummary(runId).then((response) => response.data)))
      }
      if (hasArtifact('cross_species/')) {
        baseQueries.push(warm(['phase4-cross-species-summary', runId], () => phase4Api.crossSpeciesSummary(runId).then((response) => response.data)))
      }
      if (hasArtifact('drift/')) {
        baseQueries.push(warm(['phase4-drift-summary', runId], () => phase4Api.driftSummary(runId).then((response) => response.data)))
      }
      if (artifactPaths.includes('phase5_summary.json')) {
        baseQueries.push(warm(['phase5-summary', runId], () => phase5Api.summary(runId).then((response) => response.data)))
      }
      if (hasArtifact('gene_loss/')) {
        baseQueries.push(warm(['phase5-gene-loss-summary', runId], () => phase5Api.geneLossSummary(runId).then((response) => response.data)))
      }
      if (hasArtifact('ml/phase6_summary.json')) {
        baseQueries.push(warm(['phase6-summary', runId, 'human'], () => phase6Api.summary(runId, 'human').then((response) => response.data)))
      }
      if (hasArtifact('ml/mouse/phase6_summary.json')) {
        baseQueries.push(warm(['phase6-summary', runId, 'mouse'], () => phase6Api.summary(runId, 'mouse').then((response) => response.data)))
      }
      await Promise.allSettled(baseQueries)
      if (cancelled) return

      const summary = queryClient.getQueryData<Summary>(['phase3-summary', runId])
      const comparisons = summary?.differential_expression ?? []
      const degTasks = comparisons.map(({ species, comparison }) => () =>
        warm(['phase3-deg-all', runId, species, comparison], () => fetchAllDeg(runId, species, comparison))
          .then(async () => {
            const artifactKey = ['phase3-deg-artifacts', runId, species, comparison] as const
            await warm(artifactKey, () =>
              phase3Api.degArtifacts(runId, species, comparison).then((response) => (response.data as { items: string[] }).items),
            )
            const artifactNames = queryClient.getQueryData<string[]>(artifactKey) ?? []
            for (const filename of ['volcano.png', 'ma_plot.png']) {
              if (artifactNames.includes(filename)) {
                await warm(['phase3-deg-artifact', runId, species, comparison, filename], () =>
                  phase3Api.degArtifact(runId, species, filename, comparison).then((response) => response.data as Blob),
                )
              }
            }
          }),
      )
      for (let index = 0; index < degTasks.length && !cancelled; index += 3) {
        await Promise.allSettled(degTasks.slice(index, index + 3).map((task) => task()))
      }

      if (cancelled) return
      const networks = queryClient.getQueryData<Network[]>(['phase3-networks', runId]) ?? []
      const networkTasks = networks.flatMap((network) => [
        () => warm(
          ['phase3-network-nodes', runId, network.network_id],
          () => phase3Api.nodes(runId, network.network_id, NETWORK_NODE_LIMIT, 0).then((response) => response.data),
        ),
        () => warm(
          ['phase3-network-edges', runId, network.network_id],
          () => phase3Api.edges(runId, network.network_id, NETWORK_EDGE_LIMIT, 0).then((response) => response.data),
        ),
      ])
      for (let index = 0; index < networkTasks.length && !cancelled; index += 4) {
        await Promise.allSettled(networkTasks.slice(index, index + 4).map((task) => task()))
      }

      if (cancelled) return
      const phase5Tasks: Array<() => Promise<void>> = [
      ]
      if (hasArtifact('biomarkers/candidate_biomarkers.csv')) {
        phase5Tasks.push(() => warmPaged(
          (page) => ['phase5-biomarkers', runId, page],
          (page) => phase5Api.table(runId, 'biomarkers', PAGE_SIZE, page * PAGE_SIZE).then((response) => response.data as ResultPage),
        ))
      }
      if (hasArtifact('hub_genes/')) {
        phase5Tasks.push(
          () => warm(['phase5-hub-summary', runId], () => phase5Api.summary(runId).then((response) => response.data)),
          ...(['hub-human-cancer', 'hub-human-healthy', 'hub-mouse-cancer', 'hub-mouse-healthy'] as const).map((table) => () =>
            warmPaged(
              (page) => ['phase5-hub-table', runId, table, page],
              (page) => phase5Api.table(runId, table, PAGE_SIZE, page * PAGE_SIZE).then((response) => response.data as ResultPage),
            ),
          ),
        )
      }
      if (hasArtifact('pathways/key_drifted_pathways.csv')) {
        phase5Tasks.push(() => warmPaged(
          (page) => ['phase5-key-drifted-pathways', runId, 'significant_deg', page],
          (page) => phase5Api.table(runId, 'key-drifted-pathways', PAGE_SIZE, page * PAGE_SIZE, { gene_set_key: 'significant_deg' })
            .then((response) => response.data as ResultPage),
        ))
      }
      if (hasArtifact('pathways/gene_sets.csv')) {
        phase5Tasks.push(() => warm(['phase5-pathway-gene-sets', runId, 'all'], () => phase5Api.pathwayGeneSets(runId).then((response) => response.data)))
      }
      if (hasArtifact('pathways/enrichment_results.csv')) {
        phase5Tasks.push(() => warmPaged(
          (page) => ['phase5-pathway-results', runId, 'pathway-enrichment', 'all', 'all', 'all', false, page],
          (page) => phase5Api.table(runId, 'pathway-enrichment', PAGE_SIZE, page * PAGE_SIZE)
            .then((response) => response.data as ResultPage),
        ))
        phase5Tasks.push(() => warmPaged(
          (page) => ['phase5-pathway-results', runId, 'pathway-comparisons', 'all', 'all', 'all', false, page],
          (page) => phase5Api.table(runId, 'pathway-comparisons', PAGE_SIZE, page * PAGE_SIZE)
            .then((response) => response.data as ResultPage),
        ))
      }
      if (hasArtifact('morphology/phenotype_variables.csv')) {
        for (const table of ['phenotype-variables', 'phenotype-samples'] as const) {
          phase5Tasks.push(() => warmPaged(
            (page) => ['phase5-morphology', runId, table, page],
            (page) => phase5Api.table(runId, table, PAGE_SIZE, page * PAGE_SIZE).then((response) => response.data as ResultPage),
          ))
        }
      }
      if (hasArtifact('gene_loss/gene_loss_scores.csv')) {
        for (const table of ['gene-loss', 'high-risk', 'gene-loss-evidence'] as const) {
          phase5Tasks.push(() => warmPaged(
            (page) => ['phase5-gene-loss-table', runId, table, page],
            (page) => phase5Api.table(runId, table, PAGE_SIZE, page * PAGE_SIZE).then((response) => response.data as ResultPage),
          ))
        }
      }
      for (let index = 0; index < phase5Tasks.length && !cancelled; index += 4) {
        await Promise.allSettled(phase5Tasks.slice(index, index + 4).map((task) => task()))
      }

      if (cancelled) return
      const orthologyTasks: Array<() => Promise<void>> = []
      if (hasArtifact('orthology/orthologs.csv')) {
        orthologyTasks.push(() => warmPaged(
          (page) => ['phase4-orthology-mappings', runId, page],
          (page) => phase4Api.orthology(runId, PAGE_SIZE, page * PAGE_SIZE).then((response) => response.data as ResultPage),
        ))
      }
      if (hasArtifact('cross_species/')) {
        orthologyTasks.push(
          () => warmPaged(
            (page) => ['phase4-cross-species-nodes', runId, page],
            (page) => phase4Api.crossSpeciesNodes(runId, PAGE_SIZE, page * PAGE_SIZE).then((response) => response.data as ResultPage),
          ),
          () => warmPaged(
            (page) => ['phase4-cross-species-edges', runId, '', page],
            (page) => phase4Api.crossSpeciesEdges(runId, '', PAGE_SIZE, page * PAGE_SIZE).then((response) => response.data as ResultPage),
          ),
        )
      }
      if (hasArtifact('drift/')) {
        orthologyTasks.push(
          () => warmPaged(
            (page) => ['phase4-drift-genes', runId, page],
            (page) => phase4Api.driftGenes(runId, PAGE_SIZE, page * PAGE_SIZE).then((response) => response.data as ResultPage),
          ),
          () => warmPaged(
            (page) => ['phase4-drift-edges', runId, '', page],
            (page) => phase4Api.driftEdges(runId, '', PAGE_SIZE, page * PAGE_SIZE).then((response) => response.data as ResultPage),
          ),
          () => warmPaged(
            (page) => ['phase4-drift-modules', runId, page],
            (page) => phase4Api.driftModules(runId, PAGE_SIZE, page * PAGE_SIZE).then((response) => response.data as ResultPage),
          ),
        )
      }
      if (hasArtifact('ml/out_of_fold_predictions.csv')) {
        orthologyTasks.push(
          () => warmPaged(
            (page) => ['phase6-predictions', runId, 'human', page],
            (page) => phase6Api.predictions(runId, PAGE_SIZE, page * PAGE_SIZE, 'human').then((response) => response.data as ResultPage),
          ),
          () => warmPaged(
            (page) => ['phase6-biomarkers', runId, 'human', page],
            (page) => phase6Api.biomarkers(runId, PAGE_SIZE, page * PAGE_SIZE, 'human').then((response) => response.data as ResultPage),
          ),
          ...(['logistic_regression', 'random_forest', 'svm', 'gradient_boosting'] as const).map((model) => () =>
            warmPaged(
              (page) => ['phase6-feature-importance', runId, 'human', model, page],
              (page) => phase6Api.featureImportance(runId, model, PAGE_SIZE, page * PAGE_SIZE, 'human').then((response) => response.data as ResultPage),
            ),
          ),
          ...(['roc_curves.svg', 'precision_recall_curves.svg', 'calibration_curves.svg'] as const)
            .filter((filename) => hasArtifact(`ml/${filename}`))
            .map((filename) => () => warm(['phase6-plot', runId, 'human', filename], () =>
              phase6Api.artifact(runId, filename, 'human').then((response) => response.data),
            )),
        )
      }
      for (let index = 0; index < orthologyTasks.length && !cancelled; index += 4) {
        await Promise.allSettled(orthologyTasks.slice(index, index + 4).map((task) => task()))
      }
    }

    void preload()
    return () => { cancelled = true }
  }, [queryClient, runId])

  return null
}
