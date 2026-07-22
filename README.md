# NFL ML Pipeline (AWS)

End-to-end system that predicts NFL regular-season game outcomes — winner, points,
total yards, passing yards and rushing yards per team — with weekly, continuously
updated predictions. Built as a master's thesis project (Applied Data Science),
with a full **end-to-end architecture deployed on AWS**: automated ingestion,
managed storage, model training and prospective weekly prediction across the season.

> Public subset of a larger project. Credentials, data, and infrastructure resources
> (endpoints, ARNs, VPC) are not included.

## AWS architecture

```
                 ┌─────────────────── AWS ───────────────────┐
                 │                                            │
 External APIs   │   ┌──────────────┐      ┌──────────────┐   │
 Tank01/RapidAPI ├──►│  EC2         │─────►│  Lambda      │───┼──► RDS
 nfl_data_py     │   │  ingestion + │ boto3│  secure      │   │   PostgreSQL
                 │   │  training    │invoke│  insertion   │   │
 EventBridge ───►│   └──────┬───────┘      └──────────────┘   │
 (weekly cron)   │          │                                 │
                 │          └──► SSM Parameter Store           │
                 │               (state: last processed week)  │
                 └────────────────────────────────────────────┘
```

| AWS service | Role |
|---|---|
| **EC2** | Runs the ingestion scripts (`rapidapi.py`, `get_ngs.py`) and the prediction pipeline (`team_model.py`). |
| **EventBridge** | Schedules the weekly crons that trigger ingestion and prediction. |
| **Lambda** | Receives chunked data and inserts it securely into RDS (one function per data source). |
| **RDS (PostgreSQL 15)** | Managed relational storage. Composite primary keys make loads idempotent. |
| **SSM Parameter Store** | Holds pipeline state (last processed week, season, season start) for idempotent ingestion. |

- **Idempotent ingestion**: `rapidapi.py` uses SSM to remember the last processed
  week; it validates that every game is Final before ingesting, and returns *exit
  codes* so EventBridge can retry automatically.
- **Robust delivery to Lambda**: `get_ngs.py` splits data into size-based chunks with
  exponential backoff and a 2-record test send before the full payload.

## Contents

### Data ingestion
| File | Description |
|---|---|
| `rapidapi.py` | Boxscores and schedule from Tank01 (RapidAPI). Automatic week detection via SSM, validation that all games are final, delivery to Lambda. |
| `get_ngs.py` | Next Gen Stats (passing/rushing/receiving) via `nfl_data_py`, chunked delivery to Lambda. |
| `schedule_model.py` | Data models for the schedule and game status. |
| `lambdas/rapidapi_data_lambda.py` | Lambda that upserts schedule and boxscores (games, player/team stats, scoring plays, DST) into RDS. |
| `lambdas/ngs_data_lambda.py` | Lambda that inserts Next Gen Stats (passing/receiving/rushing) into RDS. |

### Prediction model (production)
| File | Description |
|---|---|
| `team_model.py` | The system that ran in production during the 2025 season. Class `NFLDynamic2025System`: loads data, engineers 100+ features, trains one ElasticNet per metric (points, total/passing/rushing yards), predicts each week and saves to PostgreSQL, comparing against actual results. |

### Analysis notebooks
> The notebooks below are the detailed analysis from the thesis and are written in
> **Spanish**. Their outputs are preserved as-is (they cannot be re-run — the RDS was
> decommissioned to save cost). The English **Results** section below summarizes them.

| File | Description |
|---|---|
| `model_comparison_analysis.ipynb` | Systematic comparison of 8 ML models across the 4 target metrics. |
| `team_model_analysis.ipynb` | Step-by-step walkthrough of `team_model.py` with EDA and model analysis. |
| `qb_analysis.ipynb`, `rb_analysis.ipynb`, `wr_analysis.ipynb` | Per-position analysis (QB / RB / WR). |
| `*_predictor_*.pkl` | Serialized trained models. |

## Results

Eight algorithms were compared under identical data and a 5-fold temporal
cross-validation, on 2023–2025 team-game data (1,598 team-game records), predicting
four continuous targets. Metrics are on the held-out test set (MAE = mean absolute
error, R² = coefficient of determination).

**Global ranking** (average rank across the four targets — lower is better):

| Rank | Model | Avg. rank |
|---|---|---|
| 1 | **ElasticNet** | 2.00 |
| 2 | Lasso | 2.75 |
| 3 | Ridge | 3.00 |
| 4 | Linear Regression | 3.25 |
| 5 | Gradient Boosting | 4.50 |
| 6 | Random Forest | 5.50 |
| 7 | KNN | 7.25 |
| 8 | SVR | 7.75 |

**ElasticNet** was selected as the production model: the best overall performer and
the most consistent across all four metrics. Its test-set performance:

| Target | MAE | R² |
|---|---|---|
| Points | 5.76 | 0.386 |
| Total yards | 45.28 | 0.512 |
| Passing yards | 40.20 | 0.397 |
| Rushing yards | 27.50 | 0.480 |

Regularized linear models (ElasticNet, Lasso, Ridge) clearly outperformed the
distance- and margin-based models (KNN, SVR) on this small, high-variance dataset —
consistent with the overfitting risk of ~17 games per team per season. The model was
then used to generate prospective weekly predictions throughout the live 2025 season.

## Stack

Python 3.12 · pandas · numpy · scikit-learn · xgboost · SQLAlchemy · boto3 ·
nfl_data_py · matplotlib · seaborn · PostgreSQL · AWS (EC2, EventBridge, Lambda, RDS, SSM)

## Usage

```bash
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # fill in your credentials

python rapidapi.py          # ingest boxscores and schedule
python get_ngs.py           # ingest Next Gen Stats
python team_model.py        # train, predict next week, save to the DB
```

Required environment variables are documented in `.env.example`.
