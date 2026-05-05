import asyncio
import dataclasses
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

import mlflow
import mlflow.sklearn
import structlog
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

from app.config import Settings

log = structlog.get_logger()


@dataclasses.dataclass
class ModelBundle:
    pipeline: Any
    threshold: float
    model_version: str
    model_hash: str
    run_id: str
    reference_stats: dict


def load_model_bundle_sync(settings: Settings) -> ModelBundle:
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = MlflowClient()

    model_version_obj = None
    for alias in ("production", "staging"):
        try:
            model_version_obj = client.get_model_version_by_alias(settings.model_name, alias)
            log.info("model_loader.alias_resolved", alias=alias, version=model_version_obj.version)
            break
        except MlflowException:
            continue

    if model_version_obj is None:
        raise RuntimeError(
            f"No 'production' or 'staging' alias found for model '{settings.model_name}'"
        )

    version = model_version_obj.version
    run_id = model_version_obj.run_id

    with tempfile.TemporaryDirectory() as tmp:
        card_uri = f"runs:/{run_id}/model_card/model_card.json"
        card_path = mlflow.artifacts.download_artifacts(artifact_uri=card_uri, dst_path=tmp)
        card: dict = json.loads(Path(card_path).read_text())

        ref_uri = f"runs:/{run_id}/reference_stats/reference_stats.json"
        ref_path = mlflow.artifacts.download_artifacts(artifact_uri=ref_uri, dst_path=tmp)
        reference_stats: dict = json.loads(Path(ref_path).read_text())

    pipeline = mlflow.sklearn.load_model(f"models:/{settings.model_name}/{version}")

    log.info(
        "model_loader.loaded",
        version=version,
        threshold=card["threshold"],
        model_hash=card["model_hash"][:12],
    )

    return ModelBundle(
        pipeline=pipeline,
        threshold=float(card["threshold"]),
        model_version=version,
        model_hash=card["model_hash"],
        run_id=run_id,
        reference_stats=reference_stats,
    )


async def load_model_bundle(settings: Settings) -> ModelBundle:
    return await asyncio.to_thread(load_model_bundle_sync, settings)
