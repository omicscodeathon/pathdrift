# PathDrift

![Python 3.11](https://img.shields.io/badge/Python-3.11-blue)
![React 18](https://img.shields.io/badge/React-18-61DAFB)
![TypeScript 5.5](https://img.shields.io/badge/TypeScript-5.5-3178C6)
![PostgreSQL 15](https://img.shields.io/badge/PostgreSQL-15-4169E1)
![Research software](https://img.shields.io/badge/status-research%20software-orange)

**A research platform for exploring breast-cancer expression changes, gene
co-expression networks, and human–mouse network drift.**

PathDrift combines public and user-supplied expression datasets with quality
control, differential expression, network analysis, orthology mapping,
pathway enrichment, and exploratory model evaluation. The web application
supports dataset upload and automated single-dataset analysis; the
`pathdrift` command-line interface provides saved-run analysis stages.

> **Research use only.** PathDrift outputs are computational and exploratory.
> They are not clinically validated biomarkers, diagnostic tests, or treatment
> recommendations.

## Contents

- [Introduction](#introduction)
- [Project at a glance](#project-at-a-glance)
- [Workflow](#workflow)
- [Data sources](#data-sources)
- [Methods and calculations](#methods-and-calculations)
- [Results from the reference run](#results-from-the-reference-run)
- [Figures](#figures)
- [Installation](#installation)
- [Run an analysis](#run-an-analysis)
- [Explore, report, and download results](#explore-report-and-download-results)
- [Reproducibility and computational environment](#reproducibility-and-computational-environment)
- [Repository layout](#repository-layout)
- [Limitations and interpretation](#limitations-and-interpretation)
- [Testing](#testing)
- [References and data links](#references-and-data-links)
- [Contributors, acknowledgments, and license](#contributors-acknowledgments-and-license)
- [Citation](#citation)

## Introduction

Breast cancer remains a major cause of cancer-related illness and death among
women worldwide. Its development involves interacting molecular changes that
alter processes such as cell growth, differentiation, DNA repair, and
metabolism. Differential gene expression is useful for finding changes in
transcript abundance, but a gene-by-gene view may not capture changes in the
relationships among genes. Network medicine provides a complementary
perspective by studying disease-associated changes in connected biological
systems [2].

Mouse models are widely used to investigate mammary biology and cancer.
Comparing human and mouse expression networks can help identify similarities
and differences, provided that orthology, cohort design, assay, and
preprocessing are taken into account. A network edge in PathDrift represents a
co-expression association; it is not evidence of a direct molecular
interaction.

PathDrift asks whether network changes and their cross-species correspondence
can help characterize breast-cancer-associated biology alongside expression
changes. It is an exploratory computational platform: observational
associations do not establish causation, and the available cohorts do not
provide independent clinical validation.

## Project at a glance

| Capability | Description |
|---|---|
| Data | Upload expression matrices and sample metadata, or acquire supported public datasets. |
| Quality control | Summarize matrix validity, sample-level metrics, PCA, correlations, clustering, and flagged outliers. |
| Differential expression | Analyze raw counts with PyDESeq2 or continuous expression with Welch's t-test, according to input type. |
| Networks and modules | Build Spearman co-expression networks and identify Louvain communities. |
| Cross-species analysis | Map confident one-to-one human–mouse orthologs and compare network neighborhoods and modules. |
| Pathways | Run local-library over-representation analysis (ORA), pathway comparisons, and optional preranked GSEA. |
| Reporting | Browse saved-run outputs and download available artifacts through the Reports page. |
| Prediction | Run exploratory, patient-grouped cross-validation when the available labels and samples support it. |

The application contains both the current `pathdrift/` research workflow and
general-purpose backend bioinformatics modules. Their results and algorithms
are not interchangeable. For a saved result, use its run manifest, provenance,
and phase summary to establish how it was generated.

## Workflow

The workflow figure below summarizes the project's end-to-end analysis
concept. The web app's **Analyze dataset** action automates supported
single-dataset stages; it does not by itself perform every cross-species or
model-validation stage shown in the research workflow.

![PathDrift end-to-end workflow](frontend/public/Mermaid-preview.png)

### Web application: automated single-dataset workflow

1. Create or select a project and analysis.
2. Upload an expression matrix and its sample metadata, or acquire a supported
   dataset into the project.
3. Validate the dataset and resolve reported input errors.
4. On **Datasets**, select the dataset and choose **Analyze dataset**.
5. Follow the displayed stage status and errors, then inspect the saved
   results.

The automated workflow preprocesses data when needed, runs DEG and DEG
pathway enrichment, and attempts healthy/cancer networks, drift, and drift
pathway enrichment when there are at least **5 healthy and 5 cancer samples**.
The DEG step requires at least **2 healthy and 2 cancer samples**. A dataset
below the network threshold is not silently treated as a completed network
analysis. The action processes one selected dataset at a time; it does not
automatically combine separate human and mouse datasets into a cross-species
analysis.

### Research analysis stages

The saved-run code supports a broader, explicit sequence:

1. **Acquisition and QC:** retrieve/validate inputs, preserve provenance, and
   generate quality-control summaries.
2. **Expression analysis:** perform species- and state-specific differential
   expression where valid inputs and groups exist.
3. **Networks and modules:** construct co-expression graphs and detect
   communities.
4. **Orthology and drift:** map one-to-one orthologs and compare network
   neighborhoods, edges, and modules across species.
5. **Prioritization and pathways:** calculate gene-loss evidence,
   evidence-supported candidate genes, ORA, and pathway drift comparisons.
6. **Exploratory prediction:** evaluate within-cohort classifiers with
   patient-grouped folds where possible.

These stages are available through saved-run commands (see
[Run an analysis](#run-an-analysis)). Optional or unavailable results are
reported as such; implemented code does not imply that a method ran in a
particular analysis.

## Data sources

The repository's acquisition manifest currently records three public cohorts.
Counts below describe that manifest snapshot; individual analysis runs can
select different subsets or processing snapshots.

| Dataset | Species and role | Samples in manifest | Group composition | Expression data |
|---|---|---:|---|---|
| [TCGA-BRCA](https://portal.gdc.cancer.gov/projects/TCGA-BRCA) | Human breast carcinoma and adjacent-normal reference | 19 | 10 healthy/adjacent-normal, 9 cancer | GDC STAR counts; QC expression is log2(CPM + 1). |
| [GSE155577](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE155577) | Mouse mammary tumor cohort | 26 | 26 cancer; includes 24 in-vivo fractions and 2 cultured cell-line samples | GEO study-normalized expression. |
| [GSE116385](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE116385) | Mouse healthy mammary reference | 8 | 8 healthy samples from selected mammary cell populations | GEO-provided RPKM values and gene symbols, not raw counts. |

The Datasets page distinguishes repository-level acquired datasets from
datasets imported into a project. Only project datasets are available to that
project's analysis workflow. See [docs/DATASETS.md](docs/DATASETS.md) for
source details, sample provenance, checksums, and acquisition-QC notes.

### Cohort caveats

- GSE155577 has no healthy controls in the same study. Its comparison with
  GSE116385 is **cross-study exploratory** and is confounded by study,
  platform, processing, and sample-population differences.
- The selected GSE116385 reference combines fetal and adult mammary cell
  populations.
- TCGA sample and gene counts vary across acquisition, DEG, and Phase 6
  artifacts. The saved run reports 20 retained samples in its manifest,
  8 cancer plus 9 healthy samples for human DEG, and 20 labeled samples for
  Phase 6. The acquisition manifest separately reports 19 samples (10
  healthy and 9 cancer). These snapshots have not been reconciled and must not
  be presented as one identical cohort.
- The reference run's manifest records 15,264 GSE116385 genes in one
  processing snapshot, while the acquired supplementary matrix contains
  24,391 source-provided symbols. Use the specific artifact's provenance and
  checksum when interpreting its results.

## Methods and calculations

The detailed, code-linked descriptions of inputs, parameters, formulas, and
saved-run statuses are in
[docs/METHODS_AND_CALCULATIONS.md](docs/METHODS_AND_CALCULATIONS.md). The
summary below describes the active `pathdrift/` workflow and the reference
run, not every legacy backend implementation.

### Validation and preprocessing

Expression and metadata sample identifiers are checked for exact agreement.
The pipeline validates numeric, finite values and gene identifiers; it
normalizes Ensembl version suffixes where applicable, reports invalid or
duplicate identifiers, and aggregates duplicate raw-count genes by sum in
the acquisition QC path. Raw-count DEG rejects normalized, negative, or
non-integer inputs rather than silently changing statistical methods.

For raw counts \(x_{ij}\), counts-per-million and log transformation are:

\[
\mathrm{CPM}_{ij}=10^6\frac{x_{ij}}{\sum_i x_{ij}},
\qquad y_{ij}=\log_2(\mathrm{CPM}_{ij}+1).
\]

Already-normalized non-negative values use \(y_{ij}=\log_2(x_{ij}+1)\) when
that transformation is configured. QC reports missingness, zero fractions,
library sizes where applicable, sample correlations, PCA, and hierarchical
clustering. PCA outlier scores use robust median/MAD scaling; flagged outliers
are not excluded by default in the reference configuration.

### Differential expression

- **Raw RNA-seq counts:** PyDESeq2 two-condition design and Wald test;
  Benjamini–Hochberg (BH) adjustment. The saved human DEG analysis filters
  genes with at least 10 counts in at least 20% of samples, and calls a gene
  significant when adjusted \(p\leq0.05\) and \(|\log_2FC|\geq1\).
- **Continuous expression:** gene-wise two-sided Welch unequal-variance
  t-tests, followed by BH correction. On log2 input, the estimated
  log2-fold-change is the difference in group means; on linear input it is
  \(\log_2(\bar{x}_{case}+1)-\log_2(\bar{x}_{control}+1)\).

The saved cross-study mouse DEG uses log2 expression and is exploratory; its
significance does not resolve the cohort confounding described above.

### Co-expression networks and modules

Within a cohort, the saved network settings select up to 1,000 genes after a
variance filter, calculate pairwise Spearman correlations, and retain an
undirected edge only when \(|\rho|\geq0.7\) and BH-adjusted \(p\leq0.05\).
The edge weight is \(|\rho|\); the signed correlation is retained separately.
These are expression-association networks, not protein–protein interaction
networks.

Node summaries include degree, weighted degree, betweenness, closeness, and
eigenvector centrality. Louvain community detection uses edge weights and a
fixed seed. Modules smaller than the configured minimum size are omitted.
For two sets \(A\) and \(B\), module overlap is measured with Jaccard
similarity:

\[
J(A,B)=\frac{|A\cap B|}{|A\cup B|}.
\]

Hub support averages within-module percentile ranks across available
centrality and intramodular-connectivity measures; the saved run requires at
least two metrics and a score of at least 0.90.

### Orthology and cross-species drift

Human–mouse mappings use Ensembl Compara/BioMart records. Primary comparisons
require unambiguous, confident one-to-one orthology. For human and mapped-mouse
neighbor sets \(H_h\) and \(M_h\), the workflow calculates lost and gained
neighbors and Jaccard similarity. Gene drift is:

\[
\mathrm{drift}_h=0.5E_h+0.3(1-S_h)+0.2Q_h,
\]

where \(E_h=|H_h\setminus M_h|/|H_h|\) is the human-neighbor loss rate,
\(S_h=|H_h\cap M_h|/|H_h\cup M_h|\) is neighbor Jaccard similarity, and
\(Q_h=\min(1,|d_M-d_H|/D_{\max})\) is normalized degree difference. Empty
neighbor sets follow the explicit conventions documented in the methods
reference. Drift categories use thresholds 0.33 and 0.66.

Missing edges in estimated networks do not prove biological interaction loss.
Network density imbalance, mapping coverage, and cohort comparability affect
these scores.

### Gene prioritization and pathways

Gene-loss risk is a weighted mean of available network-drift and human
expression-loss evidence, configured at 0.5 per component; weights are
renormalized if a component is unavailable. High-risk scores are at least
0.66. A candidate gene must be a significant human DEG, have an additional
evidence category, and have cross-dimensional network support. Candidate
ranking is based on evidence-category count, adjusted \(p\)-value, absolute
fold-change, and gene ID; the method does not claim a clinical biomarker score.

Pathway ORA uses locally versioned GO, Reactome, and WikiPathways snapshots.
For a pathway with \(K\) genes in a background universe of \(N\), an input set
of size \(n\), and overlap \(k\), the one-sided hypergeometric tail probability
is:

\[
p=\Pr(X\geq k),\qquad X\sim\mathrm{Hypergeometric}(N,K,n).
\]

BH correction is performed separately by species, input gene set, and
database. Enrichment ratio is \((k/n)/(K/N)\) when defined. Multiple rows can
refer to the same pathway across different input gene sets.

Pathway gene-membership drift is \(1-2C_g/(|H|+|M|)\), where \(C_g\) is the
number of conserved ortholog pairs. Within-pathway edge drift is
\((|L_e|+|G_e|)/(|C_e|+|L_e|+|G_e|)\) for mapped lost, gained, and conserved
edges. A key-drifted pathway requires significant ORA in at least one species
and measurable within-pathway edge divergence. These measures are derived
from related data, not independent evidence.

GSEApy preranked GSEA is optional in the CLI. It was **not run** for the
reference run; `NOT_RUN` is not a negative enrichment result.

### Exploratory model evaluation

The saved human evaluation uses five-fold `StratifiedGroupKFold`, grouped by
patient. Imputation, variance filtering, feature selection, scaling, and model
fitting occur within each training fold. Out-of-fold predictions are used to
calculate ROC-AUC, average precision, accuracy, balanced accuracy, sensitivity,
specificity, precision, F1, and Brier score. Bootstrap intervals are
within-cohort estimates. The small sample size and lack of an independent
test cohort make these exploratory, not clinical performance estimates.

## Results from the reference run

The following summaries come from saved run
`1c782941-d15c-4c3a-a291-5172f1d23937`. The run is **completed overall but
Phase 5 is partial**. Counts are run-specific and should be interpreted with
the cohort caveats above.

| Analysis | Saved result | Interpretation |
|---|---:|---|
| Human raw-count DEG | 6,116 significant genes: 2,915 upregulated and 3,201 downregulated; 8 cancer and 9 healthy samples, 23,800 genes tested | PyDESeq2; FDR \(\leq0.05\), \(|\log_2FC|\geq1\). |
| Exploratory mouse cross-study DEG | 10,288 significant genes among 14,592 testable of 15,215 mapped genes | 12 tumor biological replicates versus 8 healthy samples; study and platform are confounded. Not confirmatory. |
| Gene-loss prioritization | 134 gene pairs scored; 27 categorized high risk | Evidence prioritization only; not a clinical risk estimate or proof of genomic deletion. |
| Candidate genes | 48 multi-evidence research candidates | Requires DEG plus additional evidence and network support; not clinically validated biomarkers. |
| Pathway ORA | 179,959 pathway-by-input-set rows | Rows are not unique pathways. Local annotation snapshots were used. |
| Pathway comparisons | 2,974 comparison rows; 2,224 key-drifted pathway rows | Derived, hypothesis-generating comparisons; row counts are not independent discoveries. |
| Human significant ORA rows | GO-BP 1,493; GO-MF 199; GO-CC 353; Reactome 507; WikiPathways 105 | Significant pathway-by-input-set rows, not unique pathway counts. |
| Mouse significant ORA rows | GO-BP 1,936; GO-MF 341; GO-CC 598; Reactome 0; WikiPathways 42 | Mouse Reactome annotations were absent from this saved reference; zero is not a biological negative. |
| Human Phase 6 model | Logistic-regression ROC-AUC 0.99 on 20 labeled samples | Within-cohort grouped CV only; not independent validation and not evidence of generalizable accuracy. |
| Morphology | Descriptive metadata only | ICD-O pathology metadata; no images or image-derived features, and no gene/pathway association was calculated. |
| GSEA and PPI | GSEA not run; PPI unavailable | No inference of absent pathways or protein interactions. Co-expression edges were not substituted for PPI. |

### Saved-run figures

Each figure below is a visualization of a saved artifact, not an independent
validation result.

## Figures

The gallery includes every distinct tracked figure for the reference run;
where both PNG and SVG exports exist, the PNG is shown once.

### Acquisition quality control

![Combined cohort PCA](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/qc/pca.png)

![Combined cohort sample correlations](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/qc/sample_correlation.png)

![Combined cohort sample clustering](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/qc/sample_clustering.png)

![TCGA-BRCA PCA](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/qc/TCGA-BRCA/pca.png)

![TCGA-BRCA sample correlations](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/qc/TCGA-BRCA/sample_correlation.png)

![TCGA-BRCA sample clustering](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/qc/TCGA-BRCA/sample_clustering.png)

![GSE155577 PCA](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/qc/GSE155577/pca.png)

![GSE155577 sample correlations](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/qc/GSE155577/sample_correlation.png)

![GSE155577 sample clustering](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/qc/GSE155577/sample_clustering.png)

### Differential expression

![Human TCGA-BRCA DEG volcano plot](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/deg/human/volcano.png)

![Human TCGA-BRCA DEG MA plot](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/deg/human/ma_plot.png)

![Exploratory mouse cross-study DEG volcano plot](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/deg/mouse/cross_study_exploratory/volcano.png)

![Exploratory mouse cross-study DEG MA plot](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/deg/mouse/cross_study_exploratory/ma_plot.png)

The mouse plots show the cross-study exploratory comparison, not a
same-study-confirmed tumor signature.

### Co-expression networks

![Human cancer network degree distribution](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/networks/human_cancer/degree_distribution.png)

![Human cancer network statistics](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/networks/human_cancer/network_statistics.png)

![Human cancer top-centrality subnetwork](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/networks/human_cancer/top_centrality_subnetwork.png)

![Human healthy network degree distribution](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/networks/human_healthy/degree_distribution.png)

![Human healthy network statistics](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/networks/human_healthy/network_statistics.png)

![Mouse cancer network degree distribution](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/networks/mouse_cancer/degree_distribution.png)

![Mouse cancer network statistics](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/networks/mouse_cancer/network_statistics.png)

![Mouse healthy network degree distribution](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/networks/mouse_healthy/degree_distribution.png)

![Mouse healthy network statistics](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/networks/mouse_healthy/network_statistics.png)

### Cross-species drift and prioritization

![Edge conservation summary](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/drift/figures/edge_conservation_summary.png)

![Gene drift distribution](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/drift/figures/gene_drift_distribution.png)

![Module conservation](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/drift/figures/module_conservation.png)

![Gene-loss risk distribution](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/gene_loss/gene_loss_risk_distribution.png)

![Candidate gene volcano plot](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/biomarkers/candidate_volcano.png)

### Exploratory model evaluation

![Phase 6 ROC curves](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/ml/roc_curves.svg)

![Phase 6 precision-recall curves](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/ml/precision_recall_curves.svg)

![Phase 6 calibration curves](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/ml/calibration_curves.svg)

## Downloadable reference-run tables

The following tracked result tables can be opened or downloaded directly.
The Reports page also offers the available artifacts for a selected run.
`gsea_results.csv` is listed as a saved artifact but GSEA was not run in this
reference analysis; it must not be interpreted as a negative result.

<details>
<summary>Quality control tables</summary>

- Combined QC: [sample QC](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/qc/sample_qc.csv), [PCA coordinates](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/qc/pca_coordinates.csv), [sample correlations](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/qc/sample_correlation.csv), [sample clustering](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/qc/sample_clustering.csv).
- TCGA-BRCA: [sample QC](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/qc/TCGA-BRCA/sample_qc.csv), [PCA coordinates](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/qc/TCGA-BRCA/pca_coordinates.csv), [sample correlations](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/qc/TCGA-BRCA/sample_correlation.csv), [sample clustering](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/qc/TCGA-BRCA/sample_clustering.csv).
- GSE155577: [sample QC](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/qc/GSE155577/sample_qc.csv), [PCA coordinates](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/qc/GSE155577/pca_coordinates.csv), [sample correlations](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/qc/GSE155577/sample_correlation.csv), [sample clustering](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/qc/GSE155577/sample_clustering.csv).

</details>

<details>
<summary>Differential-expression tables</summary>

- Human: [all tested genes](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/deg/human/all_genes.csv), [significant genes](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/deg/human/significant_genes.csv).
- Exploratory mouse cross-study: [all tested genes](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/deg/mouse/cross_study_exploratory/all_genes.csv), [significant genes](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/deg/mouse/cross_study_exploratory/significant_genes.csv), [gene mapping](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/deg/mouse/cross_study_exploratory/gene_mapping.csv), [sample metadata](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/deg/mouse/cross_study_exploratory/sample_metadata.csv).

</details>

<details>
<summary>Network, module, and orthology tables</summary>

- Networks: [network summary](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/networks/network_summary.csv), [human cancer nodes](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/networks/human_cancer_nodes.csv), [human healthy nodes](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/networks/human_healthy_nodes.csv), [human healthy edges](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/networks/human_healthy/human_healthy_edges.csv), [human cancer edges](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/networks/human_healthy/human_cancer_edges.csv), [mouse cancer nodes](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/networks/mouse_cancer_nodes.csv), [mouse cancer edges](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/networks/mouse_cancer_edges.csv), [mouse healthy nodes](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/networks/mouse_healthy_nodes.csv), [mouse healthy edges](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/networks/mouse_healthy_edges.csv).
- Human modules: [module assignments](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/modules/human/modules.csv), [module genes](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/modules/human/module_genes.csv), [module statistics](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/modules/human/module_statistics.csv).
- Mouse modules: [module assignments](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/modules/mouse/modules.csv), [module genes](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/modules/mouse/module_genes.csv), [module statistics](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/modules/mouse/module_statistics.csv).
- Orthology: [ortholog mappings](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/orthology/orthologs.csv), [unmapped human genes](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/orthology/unmapped_human_genes.csv), [unmapped mouse genes](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/orthology/unmapped_mouse_genes.csv).
- Cross-species alignment: [edge alignment](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/cross_species/edge_alignment.csv), [node alignment](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/cross_species/node_alignment.csv).

</details>

<details>
<summary>Drift, hubs, gene-loss, and integrated analysis tables</summary>

- Drift: [edge drift](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/drift/edge_drift.csv), [gene drift](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/drift/gene_drift.csv), [module drift](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/drift/module_drift.csv), [conserved edges](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/drift/conserved_edges.csv), [gained edges](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/drift/gained_edges.csv), [lost edges](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/drift/lost_edges.csv), [rewired edges](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/drift/rewired_edges.csv), [unmappable edges](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/drift/unmappable_edges.csv).
- Hub genes: [human cancer](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/hub_genes/human_cancer_hub_metrics.csv), [human healthy](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/hub_genes/human_healthy_hub_metrics.csv), [mouse cancer](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/hub_genes/mouse_cancer_hub_metrics.csv), [mouse healthy](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/hub_genes/mouse_healthy_hub_metrics.csv).
- Gene loss: [evidence](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/gene_loss/gene_loss_evidence.csv), [scores](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/gene_loss/gene_loss_scores.csv), [high-risk genes](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/gene_loss/high_risk_genes.csv).
- Candidates: [candidate biomarkers](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/biomarkers/candidate_biomarkers.csv), [candidate profiles](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/biomarkers/candidate_profiles.csv).
- Integrated gene evidence: [human](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/integrated/human_gene_integration.csv), [mouse](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/integrated/mouse_gene_integration.csv).

</details>

<details>
<summary>Pathway, morphology, and model-evaluation tables</summary>

- Pathways: [gene sets](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/pathways/gene_sets.csv), [pathway comparisons](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/pathways/pathway_comparisons.csv), [key drifted pathways](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/pathways/key_drifted_pathways.csv). The full ORA table is about 125 MB, is ignored by Git, and is not available as a repository download.
- Morphology: [sample pathology metadata](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/morphology/phenotype_sample_metadata.csv), [phenotype variables](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/morphology/phenotype_variables.csv).
- Model evaluation: [out-of-fold predictions](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/ml/out_of_fold_predictions.csv), [feature importance](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/ml/feature_importance.csv), [feature evidence](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/ml/feature_evidence.csv), [predictive biomarkers](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/ml/predictive_biomarkers.csv), [cross-species predictors](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/ml/cross_species_predictors.csv), [biological out-of-fold predictions](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/ml/biological_oof_predictions.csv), [biological feature importance](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/ml/biological_feature_importance.csv), [biological fold evidence](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/ml/biological_fold_evidence.csv).
- Run summaries: [Phase 5 summary](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/phase5_summary.json), [Phase 6 summary](results/runs/1c782941-d15c-4c3a-a291-5172f1d23937/ml/phase6_summary.json).

</details>

The full `pathways/enrichment_results.csv` for this run is approximately
125 MB and is intentionally excluded by `.gitignore`; it is not included in
the GitHub repository. The compact result counts above are transcribed from
the saved Phase 5 summary and detailed in
[docs/METHODS_AND_CALCULATIONS.md](docs/METHODS_AND_CALCULATIONS.md).

## Installation

### Requirements

- Docker Desktop with Docker Compose (recommended for the complete app), or
- Python 3.11, Node.js 18+, PostgreSQL 15+, and Redis 7+ for local development.

The analysis may require substantial memory for large expression matrices,
pairwise network calculations, and model evaluation. The repository does not
specify minimum CPU or RAM requirements.

### Start the complete application with Docker Compose

From the repository root in PowerShell:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and replace all placeholder passwords and the secret key with
strong private values. Do not commit `.env`.

```powershell
docker compose up --build -d
docker compose exec backend alembic upgrade head
```

Open:

- Frontend: <http://localhost:3000>
- Backend Swagger API: <http://localhost:8000/api/docs>
- Backend ReDoc: <http://localhost:8000/api/redoc>
- Celery Flower: <http://localhost:5555>

Register/sign in, create a project, and follow
[Run an analysis](#run-an-analysis). The backend and worker need access to the
configured database, Redis, uploaded data, and saved result directories.

Useful service commands:

```powershell
docker compose ps
docker compose logs -f backend worker
docker compose down
```

`docker compose down` stops the services but retains the named PostgreSQL
volume. Do not use `docker compose down -v` unless you intentionally want to
remove that database volume.

### Local development

Run PostgreSQL and Redis separately, then configure connection URLs and
secrets in `backend/.env`. The root `.env.example` is a template; set valid
local database and Redis URLs before starting the backend. The root-level CLI
loads `.env` relative to the repository root, so create/configure root `.env`
as well when using CLI commands; keep its service URLs and secrets consistent
with `backend/.env`.

PowerShell:

```powershell
py -3.11 -m venv backend\.venv
.\backend\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
Copy-Item .env.example backend\.env
```

Edit `backend/.env` with the local service URLs and secrets, then start the
API and worker in separate terminals:

```powershell
Set-Location backend
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

```powershell
Set-Location backend
celery -A app.tasks.celery_app worker --loglevel=info --concurrency=2 -Q analysis,ml,default
```

In another terminal, install and run the frontend:

```powershell
Set-Location frontend
npm ci
$env:VITE_API_BASE_URL = "http://localhost:8000"
npm run dev
```

Vite serves the development frontend at <http://localhost:5173>. For exact
dependency versions, use the pinned backend
[requirements](backend/requirements.txt) and frontend
[lockfile](frontend/package-lock.json).

## Run an analysis

### Use the web application

1. Register or sign in, then create or select a project on **Dashboard**.
2. Add data on **Datasets**:
   - Upload an expression matrix and sample metadata, or
   - Acquire a supported public dataset into the project using **Data Sources**.
3. Confirm the dataset appears under **Project datasets**. A dataset visible
   only in the public acquisition catalog is not yet a project dataset.
4. Validate the dataset and check that expression sample columns correspond
   exactly to metadata `sample_id` values.
5. Select an analysis and click **Analyze dataset** for the project dataset.
   The app creates an analysis if needed and displays each job's status or
   error.
6. Open result pages or **Reports** after processing completes.

The automatic workflow handles one selected dataset at a time. Cross-species
comparison requires compatible completed analyses for both species and is
not started by the single-dataset action.

#### Input data format

Expression matrices may be CSV, TSV, TXT, or gzipped versions. Rows represent
genes, columns represent samples, and the first column contains gene IDs.
Provide a separate sample metadata table with at least:

| Column | Requirement |
|---|---|
| `sample_id` | Must match an expression-matrix sample column exactly. |
| `disease_state` | Label samples as healthy/control/normal or cancer/tumor/disease. |

Optional metadata may include stage, batch, age, or sex. Declare whether the
expression matrix contains raw counts or already-normalized values accurately;
the pipeline rejects raw-count DEG inputs that are not non-negative integers.

### Run saved research stages from the command line

The CLI is run from the repository root after installing
`backend/requirements.txt` and configuring a reachable PostgreSQL database
and Redis where required. Create or select the configured project before
running the pipeline. The checked-in example configuration is
[configs/breast_cancer.yaml](configs/breast_cancer.yaml); update its project,
owner, dataset settings, and data paths to match your environment.

```powershell
python -m pathdrift --help
python -m pathdrift database check
python -m pathdrift run --config configs/breast_cancer.yaml
```

The `run` command prints JSON containing the generated run ID. Use that ID
for subsequent stages:

```powershell
python -m pathdrift phase3 --run-id <RUN_ID>
python -m pathdrift phase4 --run-id <RUN_ID>
python -m pathdrift phase5 --run-id <RUN_ID>
python -m pathdrift phase6 --run-id <RUN_ID> --species human
```

Individual `deg`, `networks`, `modules`, `orthology`, `cross-species`, `drift`,
`ml`, and `validation` stages are also available; check
`python -m pathdrift <stage> --help` for stage arguments. GSEA is opt-in for
Phase 5:

```powershell
python -m pathdrift phase5 --run-id <RUN_ID> --gsea
```

Stages depend on the inputs and outputs of earlier stages. Inspect the run
manifest and phase summaries before launching downstream analyses; use
`--force` only when intentionally recomputing a stage.

### Optional individual web-app stages

The interface also exposes manual preprocessing, network construction, drift,
cross-species comparison, and validation pages. These are useful for
parameterized analyses, but are separate from the automatic single-dataset
chain. Cross-species comparisons require valid one-to-one orthology records
and compatible completed species analyses.

## Explore, report, and download results

- **Dashboard** summarizes the selected saved analysis when available.
- **Differential Expression**, **Gene Networks**, **Network Drift**,
  **Pathway Enrichment**, and **Key Drifted Pathways** display saved-run
  results where those artifacts exist.
- **Reports** lists available saved-run artifacts. Select individual files
  to download them or use the available bulk-download action to retrieve a
  run archive.
- Result pages read persisted run artifacts; opening a result page does not
  rerun that analysis.

A missing artifact means that the stage was not run, was unavailable, or did
not complete. It must not be interpreted as a biological negative result.

## Reproducibility and computational environment

### Declared software environment

| Component | Declared version / configuration |
|---|---|
| Python analysis/backend | Python 3.11; backend dependencies pinned in `backend/requirements.txt`. |
| Statistical/data stack | NumPy 1.26.4, SciPy 1.13.0, pandas 2.2.2, statsmodels 0.14.2, scikit-learn 1.5.0. |
| Bioinformatics | PyDESeq2 0.4.9, GSEApy 1.1.3, GEOparse 2.0.4, NetworkX 3.3. |
| API and jobs | FastAPI 0.111.0, SQLAlchemy 2.0.30, Celery 5.4.0, Redis 5.0.4. |
| Frontend | React 18, TypeScript 5.5, Vite 5; npm dependency resolution is recorded in `frontend/package-lock.json`. |
| Database and queue | PostgreSQL 15 Alpine and Redis 7 Alpine in Compose. |
| Containers | Backend uses Python 3.11 slim; frontend build uses Node 18 Alpine and production static content is served by Nginx Alpine. |
| Randomness | Reference Phase 6 seed is 42; run-specific configuration takes precedence. |

### Services

| Service | Purpose | Compose host port |
|---|---|---:|
| `frontend` | React application served by Nginx | 3000 |
| `backend` | FastAPI API | 8000 |
| `db` | PostgreSQL application database | 5432 |
| `redis` | Celery broker/result backend | 6379 |
| `worker` | Background analysis and ML jobs; concurrency 2 in Compose | — |
| `flower` | Celery task monitoring | 5555 |

Use the exact saved inputs, parameters, local reference-library snapshots, and
phase summaries to reproduce a result. Installing the current dependency
versions alone does not recreate a saved analysis. Keep uploads, reference
data, and results on persistent storage in deployments. See
[docs/METHODS_AND_CALCULATIONS.md](docs/METHODS_AND_CALCULATIONS.md) for the
software inventory and provenance boundaries.

### Configuration and secrets

Compose reads environment values from root `.env`; the local backend loads
`backend/.env`. Relevant settings include PostgreSQL/Redis URLs, `SECRET_KEY`,
`UPLOAD_DIR`, `REPORT_DIR`, and optional `NCBI_EMAIL`/`NCBI_API_KEY` for NCBI
access. `GDC_API_URL`, `GTEX_PORTAL_URL`, and `ENSEMBL_REST_URL` have defaults.
Never commit passwords, API keys, access tokens, or `.env` files.

## Repository layout

```text
backend/                 FastAPI application, API routes, DB models, Celery tasks, migrations
configs/                 Example saved-run configuration
data/pathdrift/          Acquired expression data, manifests, and local references
docs/                    Dataset provenance and methods/calculations
frontend/                React + TypeScript web application
pathdrift/               Current acquisition, QC, analysis, and saved-run workflow
results/runs/<run-id>/   Run manifests, summaries, tables, and figures
tests/unit/              Backend and analysis unit tests
docker-compose.yml       Local multi-service environment
```

## Limitations and interpretation

1. The mouse tumor and healthy cohorts come from different GEO studies;
   disease status is confounded with study and platform.
2. Sample counts differ between saved processing stages. Resolve the
   documented discrepancies before treating artifacts as a single matched
   cohort.
3. Co-expression is association, not physical interaction or causation.
   Estimated missing edges do not prove biological deletion.
4. One-to-one orthology improves comparability but does not remove differences
   in tissue composition, assay, network size, or network density.
5. ORA, drifted pathways, and candidate genes are hypothesis-generating and
   correlated; they are not independent replications.
6. The Phase 6 cohort is small and has no independent human test set.
   The reported ROC-AUC of 0.99 is an exploratory within-cohort CV result.
7. Morphology is coded clinical metadata, not image analysis. No image-derived
   features or inferential morphology-to-gene associations were computed.
8. GSEA was not run and PPI was unavailable in the reference run.
9. PathDrift is not a diagnostic, prognostic, or treatment-selection device.

## Testing

Backend unit tests are under `tests/unit/`; run from the repository root after
installing backend requirements:

```powershell
python -m pytest tests/unit/ -v
```

Frontend checks:

```powershell
Set-Location frontend
npm ci
npm run type-check
npm run build
```

The frontend manifest also defines `npm run lint`. Test fixtures are
synthetic unless a test explicitly documents otherwise; tests do not replace
validation on independent biological cohorts.

## References and data links

### Background and methods

1. World Health Organization. [Breast cancer fact sheet](https://www.who.int/news-room/fact-sheets/detail/breast-cancer).
2. Barabási A-L, Gulbahce N, Loscalzo J. Network medicine: a network-based
   approach to human disease. *Nature Reviews Genetics*. 2011;12:56–68.
   [doi:10.1038/nrg2918](https://doi.org/10.1038/nrg2918).
3. Love MI, Huber W, Anders S. Moderated estimation of fold change and
   dispersion for RNA-seq data with DESeq2. *Genome Biology*. 2014;15:550.
   [doi:10.1186/s13059-014-0550-8](https://doi.org/10.1186/s13059-014-0550-8).
4. Benjamini Y, Hochberg Y. Controlling the false discovery rate: a practical
   and powerful approach to multiple testing. *Journal of the Royal
   Statistical Society: Series B*. 1995;57(1):289–300.
5. Blondel VD, Guillaume J-L, Lambiotte R, Lefebvre E. Fast unfolding of
   communities in large networks. *Journal of Statistical Mechanics: Theory
   and Experiment*. 2008;2008(10):P10008.
   [doi:10.1088/1742-5468/2008/10/P10008](https://doi.org/10.1088/1742-5468/2008/10/P10008).
6. Subramanian A, Tamayo P, Mootha VK, et al. Gene set enrichment analysis:
   a knowledge-based approach for interpreting genome-wide expression
   profiles. *Proceedings of the National Academy of Sciences*.
   2005;102(43):15545–15550.
   [doi:10.1073/pnas.0506580102](https://doi.org/10.1073/pnas.0506580102).

### Data and annotation resources

- [NCI Genomic Data Commons: TCGA-BRCA](https://portal.gdc.cancer.gov/projects/TCGA-BRCA)
- [NCBI GEO: GSE155577](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE155577)
- [NCBI GEO: GSE116385](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE116385)
- [Ensembl Compara](https://www.ensembl.org/info/genome/compara/index.html)
- Dataset acquisition and QC provenance: [docs/DATASETS.md](docs/DATASETS.md)

## Contributors, acknowledgments, and license

- **Contributors:** see the [GitHub contributors page](https://github.com/omicscodeathon/pathdrift/graphs/contributors).
- **Acknowledgments and funding:** no formal funding or acknowledgment statement is recorded in this repository; project maintainers should add one when applicable.
- **License:** no `LICENSE` file is present in the repository. No license is asserted here; consult the repository owner before redistributing or reusing the software.

## Citation

No PathDrift publication or DOI is recorded in the repository. Until one is
available, cite the specific repository release or commit used, along with
the saved run ID and input-data accessions. Do not cite the exploratory model
metrics as clinical validation.
