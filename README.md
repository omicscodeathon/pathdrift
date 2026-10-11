# PathDrift

**Cross-Species Gene Network Drift Detection for Early Breast Cancer State Prediction**

---

## Research Question

> Can cross-species gene-network drift between healthy and breast-cancer states identify conserved
> molecular changes that improve early breast-cancer state prediction?

PathDrift is a computational research platform designed to investigate whether network-level features
provide predictive information beyond conventional differential gene expression.

---

## Scientific Rationale

Standard breast cancer transcriptomic analysis identifies differentially expressed genes (DEGs) by
comparing healthy and cancer samples. PathDrift extends this by:

1. **Constructing gene co-expression networks** separately for healthy and disease states in both
   human and mouse.
2. **Detecting network drift** — quantifying how gene interaction patterns change between states.
3. **Comparing drift across species** — identifying changes conserved between human and mouse,
   which may reflect evolutionarily important cancer mechanisms.
4. **Using drift features for prediction** — testing whether conserved network drift improves
   machine-learning prediction of early breast cancer states beyond expression alone.

---

## Architecture

```
pathdrift/
├── backend/                   Python + FastAPI
│   ├── app/
│   │   ├── main.py            Application entry point
│   │   ├── core/              Configuration, security, logging
│   │   ├── db/                SQLAlchemy async engine
│   │   ├── models/            ORM models (PostgreSQL)
│   │   ├── schemas/           Pydantic request/response schemas
│   │   ├── api/routes/        FastAPI route handlers (all endpoints)
│   │   ├── services/          Business logic (dataset service, etc.)
│   │   ├── bio/               Bioinformatics engine
│   │   │   ├── preprocessing.py   QC + normalization pipeline
│   │   │   ├── deg.py             Differential expression analysis
│   │   │   ├── network.py         Co-expression network construction
│   │   │   ├── drift.py           Network drift detection (GNDS)
│   │   │   ├── orthology.py       Human–mouse orthology mapping
│   │   │   ├── cross_species.py   Cross-species drift comparison
│   │   │   ├── features.py        ML feature extraction
│   │   │   └── pathways.py        Pathway enrichment (gseapy)
│   │   ├── ml/
│   │   │   └── engine.py          ML training + evaluation
│   │   └── tasks/
│   │       ├── celery_app.py      Celery configuration
│   │       ├── analysis_tasks.py  Background analysis jobs
│   │       ├── ml_tasks.py        Background ML jobs
│   │       └── report_tasks.py    Report generation
│   ├── alembic/               Database migrations
│   ├── scripts/
│   │   └── seed_orthology.py  Load Ensembl orthology data
│   └── requirements.txt
├── frontend/                  React + TypeScript + Vite
│   └── src/
│       ├── api/client.ts      Typed API client (axios)
│       ├── store/             Zustand state (auth, project)
│       ├── types/index.ts     TypeScript types
│       ├── pages/             All application pages
│       ├── components/        Shared UI components
│       └── App.tsx
├── tests/
│   └── unit/                  Unit tests (preprocessing, network, ML, orthology)
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Prerequisites

- Docker + Docker Compose (recommended) **or**
- Python 3.11+, Node.js 18+, PostgreSQL 15+, Redis 7+

---

## Quick Start (Docker)

```bash
# 1. Clone the repository
git clone <repo-url>
cd pathdrift

# 2. Create your environment file
cp .env.example .env
# Edit .env — set POSTGRES_PASSWORD, REDIS_PASSWORD, SECRET_KEY

# 3. Start all services
docker-compose up -d

# 4. Apply database migrations
docker-compose exec backend alembic upgrade head

# 5. Seed orthology data (required for cross-species analysis)
docker-compose exec backend python scripts/seed_orthology.py

# 6. Open the application
# Frontend: http://localhost:3000
# Backend API docs: http://localhost:8000/api/docs
# Celery Flower: http://localhost:5555
```

---

## Local Development (without Docker)

### Backend

```bash
cd backend

# Create virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Linux/macOS

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp ../.env.example ../.env
# Edit .env with your database credentials

# Run database migrations
alembic upgrade head

# Seed orthology data
python scripts/seed_orthology.py

# Start the API server
uvicorn app.main:app --reload --port 8000

# In a separate terminal: start Celery worker
celery -A app.tasks.celery_app worker --loglevel=info -Q analysis,ml,default
```

### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
# Runs at http://localhost:5173
```

---

## Database Setup

PathDrift requires PostgreSQL 15+. Create the database manually if not using Docker:

```sql
CREATE USER pathdrift WITH PASSWORD 'your_password';
CREATE DATABASE pathdrift OWNER pathdrift;
```

Then update `DATABASE_URL` and `DATABASE_URL_SYNC` in `.env` and run:

```bash
cd backend
alembic upgrade head
```

---

## Orthology Data

Cross-species analysis requires human–mouse orthology mappings from Ensembl Compara.

```bash
# Requires NCBI_EMAIL in .env (not strictly required for Ensembl, but good practice)
cd backend
python scripts/seed_orthology.py
```

If the Ensembl REST API is unavailable, you can download orthology data manually from:
- https://www.ensembl.org/biomart/martservice
  
Select: Gene stable ID, Mouse gene stable ID, Gene name, Mouse gene name, Mouse homology type.
Save as TSV to `backend/data/ensembl_human_mouse_orthologs.tsv` and re-run the seed script.

---

## Data Format Requirements

For details about the currently acquired public cohorts and their browsing in the Datasets page, see [Acquired datasets](docs/DATASETS.md).

### Expression Matrix

- Format: CSV, TSV, TXT, or gzipped versions (.gz)
- Rows: genes (Ensembl ID recommended, e.g. ENSG00000141510)
- Columns: samples
- Values: raw counts (for RNA-seq) or normalized expression
- First column: gene identifier
- First row: sample identifiers

Example:
```
gene_id,SAMPLE_001,SAMPLE_002,SAMPLE_003
ENSG00000141510,245,312,198
ENSG00000012048,1024,987,1102
```

### Sample Metadata

- Format: CSV or TSV
- Required columns: `sample_id`, `disease_state`
- Valid disease_state values: `healthy`, `normal`, `control`, `cancer`, `tumor`, `disease`
- Optional columns: `stage`, `batch`, `age`, `sex`

Example:
```
sample_id,disease_state,stage,batch
SAMPLE_001,healthy,,batch1
SAMPLE_002,cancer,Stage_I,batch1
SAMPLE_003,cancer,Stage_II,batch2
```

---

## Analysis Workflow

This section describes the current application workflow. Most analyses are launched from
**Datasets** with one action; the individual analysis pages are available when you want to run or
inspect a stage separately.

### 1. Start the application and create an analysis

1. Start the backend, Celery worker, and frontend using the instructions above. Background jobs
   require the worker to be running.
2. Register or sign in.
3. On **Dashboard**, select or create a project.
4. Select an existing analysis, or leave the analysis unselected. Choosing **Analyze dataset**
   later will create an analysis for that dataset automatically if needed.

### 2. Add a dataset

Choose either route:

- **Upload your own data:** open **Datasets → Upload Dataset**, provide a name and species, select
  the data type, and upload the expression matrix. Upload sample metadata as well; the automatic
  DEG and network workflow depends on correctly labeled samples.
- **Acquire public data:** open **Data Sources**, search for a disease/species, select a supported
  accession, and download it into the project. Then confirm that it appears under **Project
  datasets** on the **Datasets** page. A public dataset shown only in the acquired manifest is not
  yet a project dataset for analysis.

On **Datasets**, use the validation action for the imported dataset and resolve any reported
errors before analysis. Review the data format requirements above, especially that expression
matrix columns and metadata `sample_id` values refer to the same samples.

### 3. Run the automatic workflow

1. On **Datasets**, select the analysis to attach the results to. If none is selected, the app
   creates one when analysis starts.
2. Find the dataset in **Project datasets** and click **Analyze dataset**.
3. Keep the page open to follow the **Automated workflow status**. It reports each queued or
   completed stage and displays errors rather than silently skipping failed stages.
4. Open the result pages or **Reports** after the jobs finish.

For a dataset with at least **2 healthy and 2 cancer samples**, the automatic workflow starts
differential expression (DEG). Non-normalized data is preprocessed first; data marked
**Already Normalized** goes directly to DEG. DEG pathway enrichment is then queued when DEG
completes. For datasets with at least **5 healthy and 5 cancer samples**, the workflow also builds
healthy and cancer co-expression networks, compares them with network drift, and queues drift
pathway enrichment. Network and drift analysis is skipped for smaller groups; the page explains
why. The automatic workflow analyzes one selected dataset at a time. Cross-species comparison
requires separate completed human and mouse analyses and is not automatically run for a
single-species dataset.

### 4. Run an individual stage manually (optional)

Use the Dashboard to select the project and analysis, and **Datasets** to select the dataset before
starting a manual stage.

1. **Preprocessing:** open **Preprocessing**, choose a normalization method appropriate for the
   input data, review filtering and outlier options, and click **Start preprocessing**. Monitor the
   job status until it completes. Do not apply `log2CPM` to a matrix that is already normalized.
2. **DEG:** for the normal end-to-end workflow, click **Analyze dataset** on **Datasets**; it runs
   preprocessing when needed and starts DEG afterward. The **Differential Expression** page is
   for viewing saved run-scoped DEG tables.
3. **Networks:** open **Gene Networks**, choose species, dataset, condition (Normal or Cancer),
   and network parameters, then click **Build Network**. Build one completed network per state
   before proceeding to drift.
4. **Network drift:** open **Network Drift**, choose the species and its completed normal and
   disease networks, then click **Run Drift**. The result page displays the status and drift
   summary.
5. **Cross-species comparison:** first provide one-to-one human–mouse orthology mappings using the
   Orthology setup above. Complete drift analyses for both species, then open **Cross-Species
   Comparison**, enter the human and mouse drift analysis IDs, and click **Compare Species**.
6. **Pathway results:** open **Pathway Enrichment** or **Key Drifted Pathways**, select the saved
   analysis run, and browse its available enrichment tables and comparisons. These pages display
   saved run-scoped results; they do not launch a new enrichment job from the page.
7. **Scientific drift validation (optional):** open **Validation**, enter the completed drift
   analysis ID, choose the permutation count, and click **Run validation**. This evaluates the
   saved drift result; it is separate from the automatic analysis stages.
8. **Machine-learning results:** open **Run ML Results** for a completed saved run to inspect
   available model metrics and outputs. Treat these as exploratory computational results, not
   clinical validation.

### 5. Browse and download results

1. Open **Reports** and select a saved analysis run.
2. Review the files listed by result section.
3. Click **Download** beside an individual artifact, or **Download all** to save the run's
   available artifacts as a ZIP archive.

Run-scoped pages such as **Differential Expression**, **Gene Networks**, **Network Drift**,
**Pathway Enrichment**, and **Run ML Results** display evidence recorded for the selected saved
run when that result category is present. A missing result means the stage was not run, is not
available for that run, or did not complete; it should not be interpreted as a biological
negative finding.

---

## Run-scoped Analysis Results

Run-scoped results are available as individual pages in the **Biological Analysis** sidebar section:

- Differential Expression
- Gene Networks
- Network Explorer
- Modules
- Module Explorer
- Integrated Analysis

Choose a project and analysis run to view the corresponding differential expression, network, module, or integrated results. Completed runs are discovered from their manifests under `results/runs`, and each page reads the saved artifacts for that run without rerunning the analysis. The cross-study mouse DEG comparison is explicitly exploratory.

---

## Scientific Methodology

### Network Construction

Weighted gene co-expression networks are built using Pearson or Spearman correlation.
FDR correction (Benjamini-Hochberg) is applied to correlation p-values.
Only gene pairs with |r| ≥ threshold AND adj.p ≤ FDR threshold receive edges.
Module detection uses Louvain community detection.

### Network Drift Score

The **Global Network Drift Score (GNDS)** is defined as:

```
GNDS = mean(topology_drift, weight_drift)

topology_drift = (n_gained + n_lost) / (n_healthy_edges + n_disease_edges)
weight_drift   = mean(|Δweight|) over rewired edges
```

Node-level drift uses a weighted composite of normalised topology metric changes.

### Cross-Species Conservation Score

```
CS = n_conserved_drift / n_total_significantly_drifting_genes
```

Range [0, 1]. Higher = more cross-species conserved network changes.

### Data Leakage Prevention

- Feature selection occurs inside training folds only
- StandardScaler is fit on training fold, applied to validation fold
- External validation datasets never influence any training step
- The system actively warns when potential leakage is detected

---

## API Documentation

Once running, view the interactive API documentation at:
- Swagger UI: `http://localhost:8000/api/docs`
- ReDoc: `http://localhost:8000/api/redoc`

---

## Running Tests

```bash
cd backend
pytest tests/unit/ -v
```

Tests use synthetic/random data and do NOT require a database connection.
No real biological data is used in tests.

---

## Configuration Reference

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | Yes | JWT signing key (generate with `python -c "import secrets; print(secrets.token_hex(64))"`) |
| `POSTGRES_PASSWORD` | Yes | PostgreSQL password |
| `REDIS_PASSWORD` | Yes | Redis password |
| `DATABASE_URL` | Yes | Async database URL (asyncpg) |
| `DATABASE_URL_SYNC` | Yes | Sync database URL (psycopg2, for Alembic/Celery) |
| `NCBI_EMAIL` | Recommended | Required for NCBI GEO import |
| `NCBI_API_KEY` | Optional | Increases NCBI rate limit |
| `MAX_UPLOAD_SIZE_MB` | Optional | Default: 500 |
| `DEFAULT_RANDOM_SEED` | Optional | Default: 42 |

---

## Important Scientific Notes

1. Results are computational predictions. They are not validated clinical biomarkers.
2. Cross-validation performance is an estimate, not a clinical guarantee.
3. Network drift scores are relative — they describe change between states within a dataset.
4. Cross-species conservation scores depend on the quality of orthology data.
5. Pathway enrichment identifies computationally associated biological processes only.
6. Early-stage prediction is only valid when the dataset contains appropriate staging metadata.
7. If a dataset lacks early-stage samples, the system reports this limitation rather than fabricating early-stage results.

---

## Deployment

For production deployment:

1. Set `ENVIRONMENT=production` in `.env`
2. Generate strong, unique `SECRET_KEY`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`
3. Configure reverse proxy (nginx/traefik) for HTTPS
4. Add your domain to `ALLOWED_HOSTS` and `CORS_ORIGINS`
5. Use persistent volumes for `uploads/` and `reports/`
6. Set up regular database backups

---

## License

PathDrift is developed for academic research. See LICENSE for details.

---

## Citation

If you use PathDrift in your research, please cite:
> [Citation to be added after publication]
