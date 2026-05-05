import hashlib
import json
import platform
import tempfile
from pathlib import Path
from typing import Any

import joblib
import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
import sklearn
import structlog
from imblearn.over_sampling import SMOTE
from imblearn.pipeline import Pipeline as ImbPipeline
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (
    GradientBoostingClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import RandomizedSearchCV, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

log = structlog.get_logger()

TARGET = "y"
PDAYS_SENTINEL = 999
MODEL_NAME = "bank_churn_classifier"
MLFLOW_URI = "http://localhost:5000"
MIN_AUC = 0.75
MIN_RECALL = 0.75

NUMERIC_COLS: list[str] = [
    "age", "campaign", "previous", "pdays_contacted",
    "emp_var_rate", "cons_price_idx", "cons_conf_idx",
    "euribor3m", "nr_employed",
]
CAT_COLS: list[str] = [
    "job", "marital", "education", "default",
    "housing", "loan", "contact", "month",
    "day_of_week", "poutcome",
]


def load_and_clean() -> pd.DataFrame:
    import kagglehub
    dataset_dir = Path(kagglehub.dataset_download("sahistapatel96/bankadditionalfullcsv"))
    csv_path = next(dataset_dir.rglob("bank-additional-full.csv"))
    df = pd.read_csv(csv_path, sep=";")
    df.columns = df.columns.str.replace(".", "_", regex=False)
    df = df.drop(columns=["duration"])
    df["pdays_contacted"] = (df["pdays"] != PDAYS_SENTINEL).astype(int)
    df = df.drop(columns=["pdays"])
    df[TARGET] = (df[TARGET] == "yes").astype(int)
    log.info("data.loaded", rows=len(df), positive_rate=round(df[TARGET].mean(), 4))
    return df


def make_pipeline(classifier: Any) -> Pipeline:
    pre = ColumnTransformer(transformers=[
        ("num", StandardScaler(), NUMERIC_COLS),
        ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CAT_COLS),
    ])
    return Pipeline(steps=[("preprocessor", pre), ("classifier", classifier)])


def make_smote_pipeline(classifier: Any) -> ImbPipeline:
    pre = ColumnTransformer(transformers=[
        ("num", StandardScaler(), NUMERIC_COLS),
        ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CAT_COLS),
    ])
    return ImbPipeline(steps=[
        ("preprocessor", pre),
        ("smote", SMOTE(random_state=42)),
        ("classifier", classifier),
    ])


def find_threshold(probs: np.ndarray, y: pd.Series, min_recall: float = MIN_RECALL) -> float:
    for t in np.arange(0.95, 0.00, -0.01):
        threshold = round(float(t), 2)
        if recall_score(y, (probs >= threshold).astype(int), zero_division=0) >= min_recall:
            return threshold
    return 0.5


def compare_models(
    X_train: pd.DataFrame, y_train: pd.Series,
    X_val: pd.DataFrame, y_val: pd.Series,
) -> dict[str, Pipeline]:
    candidates: dict[str, Any] = {
        "LogisticRegression":   LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42),
        "RandomForest":         RandomForestClassifier(n_estimators=200, class_weight="balanced", random_state=42, n_jobs=-1),
        "GradientBoosting":     GradientBoostingClassifier(n_estimators=200, learning_rate=0.05, max_depth=4, random_state=42),
        "HistGradientBoosting": HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_depth=4, random_state=42),
    }
    trained: dict[str, Pipeline] = {}
    for name, clf in candidates.items():
        pipe = make_pipeline(clf)
        pipe.fit(X_train, y_train)
        auc = roc_auc_score(y_val, pipe.predict_proba(X_val)[:, 1])
        trained[name] = pipe
        log.info("model.compared", model=name, val_auc=round(auc, 4))
    return trained


def select_imbalance_strategy(
    trained_models: dict[str, Pipeline],
    X_train: pd.DataFrame, y_train: pd.Series,
    X_val: pd.DataFrame, y_val: pd.Series,
) -> tuple[str, Any, float]:
    hgbm_kwargs: dict[str, Any] = dict(max_iter=200, learning_rate=0.05, max_depth=4, random_state=42)

    smote_pipe = make_smote_pipeline(HistGradientBoostingClassifier(**hgbm_kwargs))
    smote_pipe.fit(X_train, y_train)

    balanced_pipe = make_pipeline(HistGradientBoostingClassifier(**hgbm_kwargs, class_weight="balanced"))
    balanced_pipe.fit(X_train, y_train)

    variants: dict[str, Any] = {
        "HistGBM baseline":       trained_models["HistGradientBoosting"],
        "HistGBM + SMOTE":        smote_pipe,
        "HistGBM + class_weight": balanced_pipe,
    }

    eligible: list[tuple] = []
    for name, pipe in variants.items():
        probs = pipe.predict_proba(X_val)[:, 1]
        threshold = find_threshold(probs, y_val)
        auc = roc_auc_score(y_val, probs)
        rec = recall_score(y_val, (probs >= threshold).astype(int), zero_division=0)
        log.info("imbalance.variant", name=name, val_auc=round(auc, 4), val_recall=round(rec, 4), threshold=threshold)
        if auc >= MIN_AUC and rec >= MIN_RECALL:
            eligible.append((name, pipe, threshold))

    if not eligible:
        raise RuntimeError("No imbalance variant met AUC >= 0.75 AND recall >= 0.75")

    best = max(eligible, key=lambda x: x[2])
    log.info("imbalance.selected", winner=best[0], threshold=best[2])
    return best[0], best[1], best[2]


def tune_hyperparams(X_train: pd.DataFrame, y_train: pd.Series) -> RandomizedSearchCV:
    param_grid: dict[str, list[Any]] = {
        "classifier__max_iter":          [100, 200, 300, 400],
        "classifier__learning_rate":     [0.01, 0.05, 0.1, 0.2],
        "classifier__max_depth":         [3, 4, 5, 6, None],
        "classifier__min_samples_leaf":  [10, 20, 30, 50],
        "classifier__l2_regularization": [0.0, 0.1, 0.5, 1.0],
        "classifier__max_leaf_nodes":    [15, 31, 63, None],
    }
    search = RandomizedSearchCV(
        make_pipeline(HistGradientBoostingClassifier(random_state=42)),
        param_distributions=param_grid,
        n_iter=30, scoring="roc_auc", cv=3,
        random_state=42, n_jobs=-1, verbose=1,
    )
    search.fit(X_train, y_train)
    log.info("tuning.complete", best_cv_auc=round(search.best_score_, 4), best_params=search.best_params_)
    return search


def build_final_pipeline(best_name: str, best_params: dict[str, Any]) -> Any:
    clf_kwargs: dict[str, Any] = {**best_params, "random_state": 42}
    if "SMOTE" in best_name:
        return make_smote_pipeline(HistGradientBoostingClassifier(**clf_kwargs))
    if "class_weight" in best_name:
        return make_pipeline(HistGradientBoostingClassifier(**clf_kwargs, class_weight="balanced"))
    return make_pipeline(HistGradientBoostingClassifier(**clf_kwargs))


def compute_reference_stats(X_train: pd.DataFrame, y_train: pd.Series) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "numeric_cols": NUMERIC_COLS,
        "cat_cols": CAT_COLS,
        "numerics": {},
        "categoricals": {},
        "output": {"positive_rate": float(y_train.mean())},
    }
    for col in NUMERIC_COLS:
        arr = X_train[col].dropna().to_numpy().astype(float)
        counts, bin_edges = np.histogram(arr, bins=10)
        stats["numerics"][col] = {
            "mean": float(X_train[col].mean()),
            "std": float(X_train[col].std()),
            "bin_edges": bin_edges.tolist(),
            "reference_pct": (counts / counts.sum()).tolist(),
        }
    for col in CAT_COLS:
        vc = X_train[col].value_counts(normalize=True)
        stats["categoricals"][col] = {k: float(v) for k, v in vc.items()}
    return stats


def main() -> None:
    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment("drift-triage-training")

    df = load_and_clean()
    X = df.drop(columns=[TARGET])
    y = df[TARGET]

    X_train, X_temp, y_train, y_temp = train_test_split(X, y, test_size=0.40, stratify=y, random_state=42)
    X_val, X_test, y_val, y_test = train_test_split(X_temp, y_temp, test_size=0.50, stratify=y_temp, random_state=42)
    log.info("data.split", train=len(X_train), val=len(X_val), test=len(X_test))

    trained_models = compare_models(X_train, y_train, X_val, y_val)
    best_name, pipeline, _ = select_imbalance_strategy(trained_models, X_train, y_train, X_val, y_val)

    search = tune_hyperparams(X_train, y_train)
    best_params = {k.replace("classifier__", ""): v for k, v in search.best_params_.items()}

    pipeline = build_final_pipeline(best_name, best_params)
    pipeline.fit(X_train, y_train)
    log.info("final_pipeline.trained", best_name=best_name)

    operating_threshold = find_threshold(pipeline.predict_proba(X_val)[:, 1], y_val)
    log.info("threshold.tuned", operating_threshold=operating_threshold)

    test_probs = pipeline.predict_proba(X_test)[:, 1]
    test_preds = (test_probs >= operating_threshold).astype(int)
    test_auc = roc_auc_score(y_test, test_probs)
    test_f1 = f1_score(y_test, test_preds, zero_division=0)
    test_precision = precision_score(y_test, test_preds, zero_division=0)
    test_recall = recall_score(y_test, test_preds, zero_division=0)
    log.info("test.metrics", auc=round(test_auc, 4), recall=round(test_recall, 4),
             precision=round(test_precision, 4), f1=round(test_f1, 4))

    assert test_auc >= MIN_AUC, f"Promotion gate failed: test_auc {test_auc:.4f} < {MIN_AUC}"
    assert test_recall >= MIN_RECALL, f"Promotion gate failed: test_recall {test_recall:.4f} < {MIN_RECALL}"

    ref_stats = compute_reference_stats(X_train, y_train)
    ref_stats_path = Path(__file__).parent / "reference_stats.json"
    ref_stats_path.write_text(json.dumps(ref_stats, indent=2))
    log.info("reference_stats.saved", path=str(ref_stats_path))

    npy_path = Path(__file__).parent / "test_predictions_reference.npy"
    np.save(str(npy_path), test_probs)
    log.info("fidelity_reference.saved", path=str(npy_path))

    tmp_dir = Path(tempfile.mkdtemp())
    model_local = tmp_dir / "model_pipeline.pkl"
    joblib.dump(pipeline, model_local)
    model_hash = hashlib.sha256(model_local.read_bytes()).hexdigest()

    with mlflow.start_run() as run:
        mlflow.log_params({
            "model_type":         "HistGradientBoostingClassifier",
            "imbalance_strategy": best_name,
            "tuned_params":       str(best_params),
            "threshold":          operating_threshold,
            "train_rows":         len(X_train),
            "val_rows":           len(X_val),
            "test_rows":          len(X_test),
        })
        mlflow.log_metrics({
            "test_auc":       test_auc,
            "test_f1":        test_f1,
            "test_precision": test_precision,
            "test_recall":    test_recall,
        })
        model_info = mlflow.sklearn.log_model(pipeline, name="model")

        schema_path = tmp_dir / "schema.json"
        schema_path.write_text(json.dumps({
            "feature_names": NUMERIC_COLS + CAT_COLS,
            "numeric_cols":  NUMERIC_COLS,
            "cat_cols":      CAT_COLS,
            "target":        TARGET,
        }, indent=2))
        mlflow.log_artifact(str(schema_path), artifact_path="schema")

        model_card_path = tmp_dir / "model_card.json"
        model_card_path.write_text(json.dumps({
            "model_hash":         model_hash,
            "model_type":         "HistGradientBoostingClassifier",
            "imbalance_strategy": best_name,
            "python_version":     platform.python_version(),
            "sklearn_version":    sklearn.__version__,
            "training_date":      pd.Timestamp.utcnow().isoformat(),
            "dataset_rows":       len(df),
            "threshold":          operating_threshold,
            "test_auc":           test_auc,
            "test_f1":            test_f1,
            "test_recall":        test_recall,
            "test_precision":     test_precision,
            "model_name":         MODEL_NAME,
        }, indent=2))
        mlflow.log_artifact(str(model_card_path), artifact_path="model_card")
        mlflow.log_artifact(str(ref_stats_path), artifact_path="reference_stats")

        run_id = run.info.run_id

    client = mlflow.tracking.MlflowClient()
    registered = mlflow.register_model(model_uri=model_info.model_uri, name=MODEL_NAME)
    client.set_registered_model_alias(name=MODEL_NAME, alias="staging", version=registered.version)
    log.info("model.registered", version=registered.version, alias="staging", run_id=run_id)

    loaded = mlflow.sklearn.load_model(f"models:/{MODEL_NAME}@staging")
    assert np.allclose(loaded.predict_proba(X_test)[:, 1], test_probs, atol=1e-12), "Fidelity check failed"
    log.info("fidelity.passed")


if __name__ == "__main__":
    main()
