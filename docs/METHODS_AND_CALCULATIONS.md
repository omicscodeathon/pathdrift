# PathDrift methods, tools, and calculations

This document describes the methods implemented in the current `pathdrift/`
analysis package and the methods recorded in the saved run
`1c782941-d15c-4c3a-a291-5172f1d23937`. A method being implemented does not mean
that it ran in that saved analysis. Run-specific statuses and provenance files
are the authority for whether an output was computed.

## 1. Analysis boundaries and interpretation

PathDrift combines expression, co-expression networks, human-mouse orthology,
network comparisons, pathway annotations, and exploratory prediction. These
measurements are observational and computational:

- Network edges are associations between expression profiles, not physical
  protein-protein interactions (PPI).
- Cross-species differences are comparisons of the available datasets and
  networks; they do not establish evolutionary, causal, or biological deletion.
- Enrichment is hypothesis-generating. It is not independent validation.
- Phase 6 cross-validation is within-cohort exploratory evaluation, not an
  independent clinical validation.
- Candidate biomarkers and gene-loss risk categories are research
  prioritization outputs, not clinical biomarkers or clinical risk estimates.

The major analysis code is organized in `pathdrift/`. The web application is a
React/TypeScript frontend and a FastAPI/Python backend. Run artifacts are saved
under `results/runs/<run-id>/`; each phase summary records actual status,
parameters, inputs, and limitations.

## 2. Data sources and provenance

The current acquisition manifest documents these public datasets and analysis
roles:

| Dataset | Species and role | Data characteristics |
|---|---|---|
| TCGA-BRCA | Human breast cancer and adjacent-normal samples | GDC STAR raw counts; PathDrift QC normalization is log2(CPM + 1). |
| GSE155577 | Mouse mammary tumor cohort | GEO-provided normalized expression; 26 source samples include 24 in-vivo EpCAM fractions and two cultured cell-line samples. |
| GSE116385 | Mouse healthy mammary reference | Eight GEO-provided normal mammary cell-population samples; expression is RPKM, not raw counts. |

Detailed source descriptions, counts, checksums, and acquisition-QC notes are in
[DATASETS.md](./DATASETS.md), the acquisition manifest, and each run's
`manifest.json` and `provenance.json`.

### Saved-run cohort snapshots are phase-specific

Do not treat all sample counts in the run as one shared analysis cohort. The
saved artifacts report different selection stages:

- The run manifest records 20 retained TCGA-BRCA samples and 44,601 QC-retained
  genes.
- Human count-based DEG records 8 cancer and 9 healthy samples after excluding
  three samples; it tests 23,800 filtered genes and reports 6,116 significant
  genes at its configured thresholds.
- Phase 6 records 20 labeled human samples (10 healthy, 10 cancer) and 18
  patient groups for grouped cross-validation, using 44,601 features before
  fold-local feature selection.
- The acquisition manifest's current summary separately describes 19 analysis
  samples (10 healthy, 9 cancer).

These are facts from separate saved snapshots, not a reconciled cohort
definition. Resolve the discrepancy between the manifest, DEG, Phase 6, and
acquisition-manifest versions before interpreting the outputs as if they came
from the same participants or sample-selection policy.
The run manifest also records 15,264 validated GSE116385 gene rows, whereas
[DATASETS.md](./DATASETS.md) describes 24,391 source-provided gene symbols in
the acquired supplementary matrix. This likely reflects different processing
snapshots; use each result's recorded source and checksum rather than assuming
the row counts refer to the same file.

The exploratory mouse tumor-versus-healthy expression comparison combines
GSE155577 with GSE116385. The saved summary records 12 tumor biological
replicates and 8 healthy samples. In-vivo EpCAM-positive and -negative tumor
fractions are paired by treatment/day/replicate, transformed to log2 expression,
then averaged to form one tumor observation per biological replicate; two
cultured cell-line samples are excluded. The normal and tumor inputs remain
different studies, platforms, sample types, and processing histories. The
comparison is explicitly cross-study exploratory and is not a matched
replication.

## 3. Input checks and preprocessing

### Identifier and matrix validation

Expression matrices are checked for unique sample columns, unique gene IDs after
Ensembl version-suffix normalization, finite numeric values, and an exact match
between expression sample IDs and metadata sample IDs. Species-specific Ensembl
ID patterns are applied where the analysis requires Ensembl IDs. Invalid IDs
are removed and reported; duplicate raw-count genes are aggregated by sum in
the acquisition QC path. Raw-count DEG rejects normalized, negative, or
non-integer inputs rather than silently switching statistical methods.

Source gene-symbol mappings are restricted to unique mappings where the
workflow requires a symbol-to-Ensembl conversion. No arbitrary choice is made
when a mapping is ambiguous.

### Acquisition QC

The QC workflow reports input shape, invalid/duplicate IDs, missingness, zero
fractions, library size when applicable, PCA coordinates, outlier flags,
sample correlations, and hierarchical clusters. For the current run, the
recorded QC defaults are:

- minimum expression: 1.0 in at least 3 samples;
- maximum gene and sample missing fraction: 0.20;
- PCA uses at most the 2,000 highest-variance genes;
- robust PCA-distance outlier threshold: absolute robust z-score > 3.5;
- `exclude_outliers` is false, so flagged outliers are retained;
- missing values remaining after filtering are imputed per gene by its median.

For a raw-count sample \(j\), CPM normalization and log transformation are:

\[
\mathrm{CPM}_{ij} = 10^6 \frac{x_{ij}}{\sum_i x_{ij}}, \qquad
y_{ij} = \log_2(\mathrm{CPM}_{ij} + 1).
\]

For already normalized non-negative expression:

\[
y_{ij} = \log_2(x_{ij} + 1)
\]

when log2 normalization is configured. A `none` configuration preserves
normalized values as numeric values. In the current run, TCGA-BRCA uses
log2(CPM + 1), GSE155577 is kept as normalized, and the separate GSE116385
processed matrix is recorded as log2(RPKM + 1).

PCA uses centered input through scikit-learn's PCA implementation. For QC
outlier scoring, each sample's PCA coordinates are standardized by component
standard deviation, Euclidean distance from the PCA centroid is calculated,
and a median/MAD robust z-score is used:

\[
z_i = 0.6745 \frac{d_i-\operatorname{median}(d)}
                        {\operatorname{MAD}(d)}.
\]

If MAD is zero, the implementation falls back to the ordinary sample standard
deviation; if that is also zero, scores are zero. Outlier exclusion is
configuration-controlled; the current run flags but retains flagged samples.
Sample-to-sample correlations are Pearson correlations of normalized
expression. Clustering uses average linkage with correlation distance.

QC filtering is not a substitute for DEG's raw-count filtering; the two stages
have separate inputs and thresholds.

## 4. Differential expression

The active DEG implementation is in
[analysis.py](../pathdrift/differential_expression/analysis.py), with input
validation and count filtering in the neighboring
[validation.py](../pathdrift/differential_expression/validation.py) and
[preprocessing.py](../pathdrift/differential_expression/preprocessing.py).

### Raw-count comparisons

Raw counts are first retained if a gene has at least the configured
`min_count` in at least
\(\lceil n_{\mathrm{samples}}\times\mathrm{min\_samples\_fraction}\rceil\)
samples. The current human DEG summary records `min_count = 10`,
`min_samples_fraction = 0.20`, and 4 required samples.

Counts are analyzed with PyDESeq2 using a two-condition design and a Wald test.
The reported fold change is cancer relative to healthy (positive means higher in
cancer). PyDESeq2 supplies the estimated log2 fold change, test statistic,
nominal p-value, and adjusted p-value. P-values are adjusted using the
Benjamini-Hochberg procedure. A gene is called significant only if both

\[
\mathrm{adjusted\_p} \leq \alpha
\quad\land\quad
|\log_2\mathrm{FC}| \geq \mathrm{lfc\_threshold}.
\]

The saved human DEG parameters are \(\alpha=0.05\) and
\(|\log_2\mathrm{FC}|\geq1\). Upregulated and downregulated counts are subsets
of genes satisfying both conditions.

### Continuous-expression comparisons

For non-count expression declared on the log2 scale, the implementation uses
Welch's unequal-variance two-sample t-test gene by gene. On a linear,
non-negative expression scale, log2 fold change is
\(\log_2(\bar{x}_{case}+1)-\log_2(\bar{x}_{control}+1)\); on log2 input it is
\(\bar{x}_{case}-\bar{x}_{control}\). Welch degrees of freedom are calculated
from the two sample variances and group sizes. The resulting two-sided p-values
are adjusted by Benjamini-Hochberg, and the same adjusted-p and absolute-fold
change thresholds classify significant genes.

The saved mouse cross-study comparison reports 15,215 shared genes, of which
14,592 had testable within-group variance; 623 genes did not have a valid
variance-based test. It reports 10,288 threshold-significant genes, but this
high count must be interpreted in light of study/platform confounding and the
exploratory status recorded in its summary.

## 5. Co-expression networks and modules

Network construction is implemented under
[networks/](../pathdrift/networks/). The saved run's network summaries identify
Spearman correlation networks. For a cohort with \(n\) samples, the network
workflow:

1. Removes genes below the configured variance threshold and caps the candidate
   genes at the configured maximum.
2. Ranks each gene's sample expression values and calculates pairwise
   Spearman correlations \(\rho_{ij}\).
3. Calculates a two-sided t-approximation p-value using \(n-2\) degrees of
   freedom:
   \[
   t = |\rho| \sqrt{\frac{n-2}{1-\rho^2}}.
   \]
4. Adjusts p-values across all tested gene pairs using Benjamini-Hochberg.
5. Retains an undirected edge only when both the absolute-correlation threshold
   and adjusted-p threshold are met. The edge weight is \(|\rho|\), while the
   signed correlation is retained as an attribute.

Networks in the saved run use 1,000 selected genes per cohort. Spearman
correlation networks describe co-expression; they are not PPI networks.

For each graph, node annotations include degree, weighted degree (sum of edge
weights), betweenness, closeness, and eigenvector centrality. Shortest-path
distance for centrality is \(1-|\rho|\), bounded away from zero in the graph.
Betweenness is deterministically sampled where needed; closeness uses a
deterministic landmark approximation above 1,000 nodes. Eigenvector
non-convergence is represented as missing and reported as such.

Communities use NetworkX Louvain with edge weight, configured resolution, and
seed. Communities smaller than the configured minimum module size are not
retained as modules. A module's reported density is
\(2E/[n(n-1)]\); average degree is the mean within-module degree. Module
summaries also include internal edge count, mean internal edge weight, top
central genes, and (where DEG input is available) DEG counts.

### Hub support

Available centrality metrics and intramodular connectivity are converted to
within-module percentile ranks. Hub score is their arithmetic mean:

\[
\mathrm{hub\_score}(g) =
\frac{1}{m_g}\sum_{k \in A_g}
\mathrm{percentile}_{module(g),k}(g),
\]

where \(A_g\) is the set of available metrics and \(m_g=|A_g|\). In the saved
run, hub support requires at least two available metrics and a score of at least
0.90. Missing metrics are omitted from the average; an unassigned module or
fewer than two metrics does not yield positive hub support.

### Module comparison

For each human module, one-to-one ortholog members are mapped to mouse genes and
compared with each mouse module. The module conservation score is Jaccard
similarity:

\[
J(A,B)=\frac{|A\cap B|}{|A\cup B|}.
\]

The maximum matching Jaccard is the best module match used in pathway
comparison. The general module-alignment code classifies the best match as
conserved at Jaccard \(\geq0.70\), partially conserved at
\(\geq0.30\) and below 0.70, or rewired below 0.30. If one human module's
mapped members are distributed across multiple mouse modules, it can instead
be classified fragmented; without mapped overlap it is not aligned. These
labels are descriptive of the selected module comparison and do not by
themselves establish biological conservation.

## 6. Orthology and cross-species network drift

Human-mouse homology is obtained from Ensembl Compara BioMart (the acquisition
code can record the current release). Version suffixes are removed from stable
Ensembl identifiers. Mapping records are classified by one-to-one, one-to-many,
many-to-one, or many-to-many relationship cardinality. Primary comparisons
require `ortholog_one2one` and unambiguous one-to-one cardinality; where the
workflow requires a confidence threshold, it uses confidence \(\geq1.0\).
The exact map and version saved with a run take precedence over the live
service.

For a mapped human gene \(h\), mouse neighbors are mapped back to human IDs.
Let \(H_h\) and \(M_h\) be its human and mapped-mouse neighbor sets. Define:

\[
\begin{aligned}
C_h &= H_h \cap M_h,\\
L_h &= H_h \setminus M_h,\\
G_h &= M_h \setminus H_h,\\
S_h &= \frac{|C_h|}{|H_h\cup M_h|},\\
E_h &= \frac{|L_h|}{|H_h|}.
\end{aligned}
\]

For empty neighbor unions, similarity is defined as 1; for empty human
neighbors, edge-loss rate is 0. Let \(d_H,d_M\) be the two gene degrees and
\(D_{max}\) the maximum degree across the compared networks (at least 1):

\[
Q_h = \min\left(1,\frac{|d_M-d_H|}{D_{max}}\right),\qquad
\mathrm{drift}_h = 0.5E_h + 0.3(1-S_h) + 0.2Q_h.
\]

The saved configuration classifies drift as low below 0.33, moderate from 0.33
to below 0.66, and high at or above 0.66. Drift is a weighted summary of
network differences; edges absent from one estimated network are not proof that
an interaction was biologically deleted. Network size and density imbalance
are recorded limitations in the saved run.

For edge-level alignment, edges are canonicalized as undirected pairs and
compared after orthology mapping. Existing pairs are classified as rewired if
the absolute difference in edge weights meets the configured threshold
(default 0.05), otherwise conserved. Human edges without a mouse counterpart
are classified lost; mapped mouse-only counterparts are gains; unmappable
edges remain explicitly unmappable. Signed weight difference is
\(w_M-w_H\); relative change is \((w_M-w_H)/|w_H|\) when \(w_H\neq0\).

## 7. Phase 5: gene-loss prioritization, pathways, and phenotype metadata

Phase 5 is `PARTIAL` for the saved run: gene-loss evidence, biomarker
prioritization, hub calculations, pathway ORA/comparisons, and descriptive
phenotype metadata completed; local preranked GSEA was not run; PPI was
unavailable.

The run summary records 134 scored gene pairs (27 categorized high risk), 48
multi-evidence research candidates, 30 pathway input gene sets, 179,959
pathway-by-gene-set ORA rows, 2,974 pathway-comparison rows, and 2,224
key-drifted pathway rows. Significant ORA rows by species/database were human
GO-BP 1,493, GO-MF 199, GO-CC 353, Reactome 507, WikiPathways 105; mouse
GO-BP 1,936, GO-MF 341, GO-CC 598, Reactome 0, WikiPathways 42. A pathway can
appear in multiple gene sets, and the Reactome zero for mouse reflects the
absence of mouse Reactome annotations in the saved reference, not a negative
biological result.

### Gene-loss score

For each drift-mapped gene pair, the network component is its gene drift score.
The human expression-loss component is 1 when the human DEG is downregulated
with FDR \(\leq0.05\) and log2FC \(\leq-1\), 0 when the human test is available
but does not meet those loss criteria, and missing when it cannot be evaluated.
The mouse DEG is reported as exploratory context and excluded from the score.

The configured component weights are 0.5 for network drift and 0.5 for human
expression loss. The actual score is a weighted mean over available components,
renormalizing weights when a component is missing:

\[
\mathrm{risk\_score} =
\frac{\sum_{k\in A} w_k x_k}{\sum_{k\in A}w_k}.
\]

The saved thresholds are low below 0.33, moderate from 0.33 to below 0.66,
and high at or above 0.66. No available components yields `NOT_SCORED`.
Absence of a recorded ortholog is not evidence of genomic deletion.

### Candidate biomarkers

A candidate must:

1. Be a significant human DEG at FDR \(\leq0.05\) and absolute log2FC
   \(\geq1\).
2. Have at least one additional evidence category.
3. Have at least one cross-dimensional network support category: multi-metric
   hub support, drift score \(\geq0.66\), or an observed lost/gained
   interaction.

DEG-only, module-only, and orthology-only evidence cannot qualify a candidate.
Eligible candidates are ordered by descending evidence-category count, then
ascending adjusted p-value, then descending absolute log2FC, then gene ID.
There is no composite biomarker score. Pathway/morphology context does not count
as clinical validation.

### Pathway gene sets and over-representation analysis (ORA)

Pathway inputs are locally versioned snapshots, not live web lookups. The saved
run used:

- GO Basic ontology and human/mouse GAF associations dated 2026-05-21.
  GO annotations are propagated to ancestors through `is_a` and `part_of`.
- Reactome GMT export modified 2026-06-21; only human Reactome terms were
  available.
- Species-specific WikiPathways GMT snapshots dated 2026-09-10.
- Local Ensembl gene-ID maps; unique symbol/Entrez mappings only.

Input sets include available saved DEG directions, drift, interaction
loss/gain, candidate biomarkers, hubs, and modules. Each library's effective
background is the database-specific expressed Ensembl universe with a valid
mapping. For a pathway, let \(N\) be universe size, \(K\) pathway genes in that
universe, \(n\) input genes in the universe, and \(k\) their pathway overlap.
The one-sided hypergeometric over-representation p-value is:

\[
p = \Pr(X\geq k), \quad X\sim\mathrm{Hypergeometric}(N,K,n).
\]

Enrichment ratio is \((k/n)/(K/N)\) when the denominators are nonzero.
Benjamini-Hochberg correction is performed separately within species, input
gene set, and database. Results with nonzero overlap are saved; significance
uses adjusted p-value \(\leq0.05\). A pathway can recur across input gene sets,
so pathway-by-gene-set rows are not unique pathway counts.

### Optional GSEA

The implementation supports local preranked GSEA through GSEApy, ranking genes
by the saved signed test statistic, deduplicating mapped symbols, and using
gene-set permutations (default 1,000), minimum set size 10, maximum 500, and
seed 42. The saved run's phase summary explicitly says `NOT_RUN`; those
parameters describe capability, not computed results. Do not interpret an
empty `gsea_results.csv` as a negative GSEA result.

### Pathway comparison and key drifted pathways

For a pathway present in both species, one-to-one ortholog gene membership is
compared. Gene-membership drift is:

\[
1-\frac{2\,C_g}{|H|+|M|},
\]

where \(C_g\) is the number of conserved ortholog pairs and \(H,M\) are the
human and mouse pathway members.

Within-pathway human edges are mapped to mouse ortholog pairs and compared with
mouse edges. If \(C_e,L_e,G_e\) denote conserved, human-only (lost), and
mouse-only (gained) mapped edges:

\[
\mathrm{pathway\_drift} =
\frac{|L_e|+|G_e|}{|C_e|+|L_e|+|G_e|}.
\]

The score is undefined for an empty mapped edge union. Module preservation is
the highest human/mouse module Jaccard among the pathway's mapped members.
Pathway presence (`both`, `human_only`, `mouse_only`) is based on ORA FDR at
0.05. A `key_drifted_pathway` requires significant ORA in at least one species
and nonzero measurable within-pathway edge divergence. These are correlated
derived measures, not independent validation; different network density is a
major limitation.

### Morphology / phenotype

The saved run's morphology status is `DESCRIPTIVE_METADATA_ONLY`. The workflow
summarizes available human clinical-pathology metadata (including stage,
diagnosis, grade, and morphology code) and selected covariates. It has no
pathology images or image-derived features, no mouse pathology record, and no
gene/pathway association calculation. In particular, the morphology field is
an ICD-O clinical pathology code, not an image measurement.

### PPI status

PPI is `UNAVAILABLE` in the saved run. Co-expression edges are not substituted
for PPI. A missing PPI result means that no PPI analysis was available for this
run; it is not evidence for absence of protein interactions.

## 8. Phase 6: exploratory prediction and validation

The human Phase 6 input is the Phase 2 processed expression matrix and
human-labeled samples. Labels are healthy = 0 and cancer = 1. The saved run
reports 20 samples, 18 patient groups, five `StratifiedGroupKFold` folds,
44,601 features before fold-local selection, and 100 selected features per
fold. All learned preprocessing and feature selection are fitted only on each
training fold:

1. Median imputation.
2. Zero-variance feature removal.
3. Top 100 features by ANOVA F-score.
4. Standard scaling.
5. Classifier fitting.

The evaluated expression-only classifiers are balanced logistic regression,
random forest (300 trees), linear SVM, and gradient boosting. Predictions
reported for model evaluation are out-of-fold probabilities. The fixed
classification threshold is 0.5. Metrics are:

- ROC-AUC: area under the receiver-operating-characteristic curve.
- PR-AUC: average precision.
- Accuracy: \((TP+TN)/(TP+TN+FP+FN)\).
- Balanced accuracy: mean of sensitivity and specificity.
- Sensitivity: \(TP/(TP+FN)\); specificity: \(TN/(TN+FP)\).
- Precision: \(TP/(TP+FP)\); F1: harmonic mean of precision and sensitivity.
- Brier score: mean squared probability error,
  \(\frac1n\sum_i(p_i-y_i)^2\).

ROC-AUC intervals use 1,000 percentile bootstrap resamples, sampling patient
groups when available. These intervals and all cross-validation scores remain
within-cohort estimates; the small sample size makes them exploratory.
Fold-local feature importance is aggregated from fold models and selection
frequency, not computed from the full-cohort model for ranking.

The saved run also evaluates biological feature experiments by deriving DEG
rankings and human cancer networks within each training fold:

- Fold-local DEG ranks use Welch's t-test on normalized log2 expression with
  Benjamini-Hochberg adjustment; DEG evidence uses adjusted p \(\leq0.05\)
  and absolute expression difference \(\geq1\).
- The fold-local human cancer network uses Spearman correlation, absolute
  correlation \(\geq0.7\), adjusted p \(\leq0.05\), minimum gene variance 0.1,
  and at most 1,000 genes. The top 50 active genes by weighted degree, degree,
  and gene ID are hub candidates.
- Drift candidates use the saved mouse cancer network as a fixed biological
  reference with confident one-to-one orthology; the top 100 gene drift scores
  are retained. This mouse reference is annotation input, not an independent
  test cohort.
- A drift-weighted experiment multiplies the selected expression column by
  \(1+\mathrm{drift\_score}\).
- The integrated panel is the intersection of significant training-fold DEGs
  and the union of hub/drift support.
- Fold-level candidate features are evaluated with median imputation,
  standardization, and balanced logistic regression.

These comparisons avoid using held-out labels to construct fold-specific
features, but they do not create external validation. The saved Phase 6
validation record says no matched independent human test cohort is available;
it also records permutation testing as not run. Mouse-only classification is
`NOT_ESTIMABLE`: GSE155577 is tumor-only and GSE116385 healthy-only, and pooling
the studies would confound disease with study.

For context, the saved expression-only out-of-fold logistic regression reports
ROC-AUC 0.99 on those 20 labeled samples. This is a small within-cohort
cross-validation result, not independent performance. The run does not claim
that this score generalizes.

## 9. Computational environment and application architecture

The repository defines a containerized, multi-service application. The exact
versions below are the declared/configured environment; they are not a claim
that every package is used by every run.

### Runtime and operating system

- **Backend and analysis:** Python 3.11, based on `python:3.11-slim`.
- **Frontend build:** Node.js 18 on Alpine Linux; production static files are
  served by Nginx on Alpine Linux.
- **Data services:** PostgreSQL 15 Alpine and Redis 7 Alpine.
- **Container platform:** Docker Compose, with Linux containers. The developer
  workstation for this repository is Windows; that is distinct from the Linux
  container runtime and does not define the production host OS.
- **Hardware:** The repository does not specify minimum CPU, RAM, disk, or GPU
  requirements. Network correlation and ML feature selection can be
  memory-intensive on large expression matrices; provision resources according
  to dataset size.

### Services and connectivity

| Service | Technology / purpose | Container port | Host port in Compose |
|---|---|---:|---:|
| `frontend` | React static build served by Nginx; proxies `/api/` to backend | 80 | 3000 |
| `backend` | FastAPI + Uvicorn API | 8000 | 8000 |
| `db` | PostgreSQL application database | 5432 | 5432 |
| `redis` | Celery broker/result backend and cache/queue service | 6379 | 6379 |
| `worker` | Celery analysis and ML task worker; concurrency 2 in Compose | — | — |
| `flower` | Celery task-monitoring UI | 5555 | 5555 |

The backend uses SQLAlchemy with an async PostgreSQL URL for API work and a
synchronous PostgreSQL driver URL for migrations/task contexts. Alembic manages
schema migrations. Celery routes analysis and validation work to an `analysis`
queue and prediction work to an `ml` queue, using Redis as broker and result
backend. Task soft and hard limits are 1 hour and 2 hours respectively.
Compose health checks gate backend/worker startup on healthy PostgreSQL and
Redis services.

PostgreSQL data persists in a named Compose volume. Backend uploads, reports,
and logs are mounted from the host into the backend container. The application
also stores analysis artifacts in the repository's data/results layout when
running from source; deployments should persist those configured directories
and any required input/reference data.

### Declared dependency and build configuration

- Backend package versions are pinned in
  [requirements.txt](../backend/requirements.txt), including FastAPI 0.111.0,
  Uvicorn 0.30.1, SQLAlchemy 2.0.30, Celery 5.4.0, NumPy 1.26.4, SciPy 1.13.0,
  pandas 2.2.2, statsmodels 0.14.2, scikit-learn 1.5.0, NetworkX 3.3,
  PyDESeq2 0.4.9, GSEApy 1.1.3, and PyArrow 18.1.0.
- Frontend dependencies and tooling are specified in
  [package.json](../frontend/package.json) and resolved by the npm v3 lockfile
  [package-lock.json](../frontend/package-lock.json). The manifest specifies
  React 18, TypeScript 5.5, and Vite 5 version ranges.
- The backend image installs native build and scientific-library prerequisites
  including BLAS/LAPACK, HDF5, PostgreSQL headers, GCC/G++, and GFortran.
- The frontend image uses `npm ci`, runs the production build, then copies the
  static output into Nginx. Its API base URL is a build argument.
- Database, Redis, JWT, storage, and optional external API configuration are
  supplied through environment variables. `.env.example` is a template only;
  credentials must be supplied locally and not committed.

### Development and verification entry points

The repository README documents a Python virtual environment, backend launch
with Uvicorn on port 8000, and frontend development through Vite. The frontend
provides `npm run dev`, `npm run build`, `npm run lint`, and
`npm run type-check`. Backend test dependencies include pytest and
pytest-asyncio; the README documents `pytest tests/unit/ -v`. Docker Compose
provides the full database, queue, API, worker, monitoring, and frontend stack.
Use the project's checked-in lockfiles and dependency manifests when setting
up a reproducible environment.

## 10. Software and service inventory

Versions are pinned in the repository manifests. Principal tools in the
analysis/runtime include:

| Area | Tools used or declared |
|---|---|
| Data and statistics | Python, pandas, NumPy, SciPy, statsmodels |
| Expression analysis | PyDESeq2; scikit-learn for Welch-based/ML and preprocessing utilities |
| Networks and modules | NetworkX |
| Enrichment | GSEApy for optional GSEA; local GO, Reactome, and WikiPathways snapshots for ORA |
| Data acquisition | GDC API, GEO/GEOparse, Ensembl REST/BioMart, HTTPX |
| Persistence and jobs | FastAPI, SQLAlchemy, PostgreSQL drivers, Celery, Redis |
| Backend plotting and reports | Matplotlib, Seaborn, Plotly, Kaleido, ReportLab, WeasyPrint, Jinja2 |
| Frontend | React, TypeScript, Vite, Material UI, TanStack Query, Axios, Zustand, Cytoscape, Plotly |
| Quality checks | pytest, mypy, TypeScript compiler, ESLint |

Packages are declared tools, not necessarily invoked in every analysis run.
External source snapshots and API versions are captured in provenance where
available; reproducibility requires the saved run's exact artifacts and
configuration, not merely installing the current dependency versions.

## 11. Implemented capability versus this saved run

| Analysis | Saved-run status | Interpretation |
|---|---|---|
| Human raw-count DEG | Completed | PyDESeq2; saved DEG cohort is 8 cancer / 9 healthy. |
| Mouse DEG, same-study cancer vs healthy | Unavailable | No same-study healthy mouse controls in the run. |
| Mouse cross-study exploratory DEG | Completed | GSE155577 vs GSE116385; not confirmatory. |
| Co-expression networks and modules | Completed | Species/state networks and Louvain modules saved. |
| Orthology and gene drift | Saved | One-to-one mapping supports network comparison; density mismatch limits claims. |
| Gene-loss and candidate ranking | Completed | Evidence prioritization only; no clinical risk inference. |
| Pathway ORA and pathway comparison | Completed | Local versioned libraries; hypothesis-generating. |
| GSEA | Not run | Optional capability; run summary explicitly reports `NOT_RUN`. |
| Morphology | Descriptive metadata only | No images, image-derived features, or inferential association. |
| PPI | Unavailable | No PPI evidence in this saved run. |
| Human ML | Exploratory, partial | Patient-grouped CV; no independent test set or permutation result. |
| Mouse ML | Not estimable | Disease and study are confounded by the available cohorts. |

## 12. Method-source index

- [Expression validation](../pathdrift/differential_expression/validation.py)
- [Raw-count filtering and DEG](../pathdrift/differential_expression/preprocessing.py), [analysis](../pathdrift/differential_expression/analysis.py)
- [Acquisition QC](../pathdrift/acquisition/qc.py)
- [Network correlation and construction](../pathdrift/networks/correlation.py), [construction](../pathdrift/networks/construction.py), [centrality](../pathdrift/networks/centrality.py)
- [Louvain modules](../pathdrift/modules/detection.py)
- [Orthology mapping](../pathdrift/orthology/mapping.py), [Ensembl acquisition](../pathdrift/orthology/ensembl.py)
- [Cross-species network drift](../pathdrift/drift/scoring.py), [edge alignment](../pathdrift/cross_species/edge_mapping.py), [module alignment](../pathdrift/cross_species/module_mapping.py)
- [Phase 5 pathway methods](../pathdrift/phase5/pathways.py), [gene-loss and candidate calculations](../pathdrift/phase5/scoring.py), [phenotype metadata](../pathdrift/phase5/phenotype.py)
- [Phase 6 evaluation](../pathdrift/phase6/evaluation.py), [biological experiments](../pathdrift/phase6/biological.py), [saved-run orchestration](../pathdrift/phase6/service.py)
- [Saved run manifest](../results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/manifest.json), [Phase 5 summary](../results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/phase5_summary.json), [Phase 6 summary](../results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/ml/phase6_summary.json)
- [Backend dependencies](../backend/requirements.txt), [frontend dependencies](../frontend/package.json)

The repository also contains older/general bioinformatics modules and a
standalone real-data script. Their methods are not interchangeable with the
active `pathdrift/` workflow described above. For a result, follow its saved
phase summary and provenance first; do not infer the method from a similarly
named legacy module.
