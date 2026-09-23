from datetime import datetime, timezone
from uuid import uuid4

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc).isoformat()


@event.listens_for(Engine, "connect")
def sqlite_settings(connection, record):
    if connection.__class__.__module__ == "sqlite3":
        cursor = connection.cursor()
        for sql in (
            "PRAGMA foreign_keys=ON",
            "PRAGMA busy_timeout=5000",
            "PRAGMA journal_mode=WAL",
        ):
            cursor.execute(sql)
        cursor.close()


class Job(db.Model):
    __tablename__ = "recognition_jobs"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    scope = db.Column(db.String(20), nullable=False, default="PRODUCTION", index=True)
    original_path = db.Column(db.Text, nullable=False)
    original_sha256 = db.Column(db.String(64), nullable=False, index=True)
    mime_type = db.Column(db.String(40), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    image_difficulty = db.Column(db.String(20), nullable=False, default="UNLABELED")
    scenario_tags = db.Column(db.JSON, nullable=False, default=list)
    group_key = db.Column(db.String(200), nullable=False, index=True)
    privacy = db.Column(db.String(20), nullable=False, default="PRIVATE")
    revision = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.String(40), nullable=False, default=now, index=True)


class Attempt(db.Model):
    __tablename__ = "recognition_attempts"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    job_id = db.Column(db.ForeignKey("recognition_jobs.id"), nullable=False, index=True)
    profile_id = db.Column(db.String(100), nullable=False)
    provider = db.Column(db.String(40), nullable=False, index=True)
    model = db.Column(db.Text, nullable=False)
    model_version = db.Column(db.Text)
    status = db.Column(db.String(30), nullable=False, default="QUEUED", index=True)
    snapshot = db.Column(db.JSON, nullable=False)
    processed_path = db.Column(db.Text)
    processed_sha256 = db.Column(db.String(64))
    normalized_ai_result = db.Column(db.JSON)
    validation_result = db.Column(db.JSON, nullable=False, default=list)
    decision_result = db.Column(db.JSON)
    repair_result = db.Column(db.JSON)
    error_code = db.Column(db.String(50))
    error_message = db.Column(db.Text)
    latency_ms = db.Column(db.Float)
    processing_ms = db.Column(db.Float)
    queue_ms = db.Column(db.Float)
    hard_reasons = db.Column(db.JSON, nullable=False, default=list)
    worker_id = db.Column(db.String(36))
    lease_until = db.Column(db.Float)
    created_at = db.Column(db.String(40), nullable=False, default=now, index=True)
    started_at = db.Column(db.String(40))
    finished_at = db.Column(db.String(40))


class Observation(db.Model):
    __tablename__ = "machine_observations"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    attempt_id = db.Column(db.ForeignKey("recognition_attempts.id"), nullable=False, index=True)
    stage = db.Column(db.String(20), nullable=False)
    provider = db.Column(db.String(40), nullable=False)
    model = db.Column(db.Text, nullable=False)
    model_version = db.Column(db.Text)
    raw_result = db.Column(db.JSON)
    output_text = db.Column(db.Text)
    confidence_kind = db.Column(db.String(40), nullable=False, default="SELF_REPORTED_ENUM")
    calibration_version = db.Column(db.String(100))
    created_at = db.Column(db.String(40), nullable=False, default=now)


class Confirmation(db.Model):
    __tablename__ = "confirmation_revisions"
    __table_args__ = (db.UniqueConstraint("job_id", "revision_no"),)
    id = db.Column(db.String(36), primary_key=True, default=uid)
    job_id = db.Column(db.ForeignKey("recognition_jobs.id"), nullable=False, index=True)
    attempt_id = db.Column(db.ForeignKey("recognition_attempts.id"), nullable=False, index=True)
    revision_no = db.Column(db.Integer, nullable=False)
    previous_revision_id = db.Column(db.ForeignKey("confirmation_revisions.id"))
    human_ground_truth = db.Column(db.JSON, nullable=False)
    validation_result = db.Column(db.JSON, nullable=False)
    review_active_ms = db.Column(db.Integer, nullable=False, default=0)
    confirmed_at = db.Column(db.String(40), nullable=False, default=now)


class FieldAnnotation(db.Model):
    __tablename__ = "field_annotations"
    __table_args__ = (db.UniqueConstraint("confirmation_id", "field_name"),)
    id = db.Column(db.String(36), primary_key=True, default=uid)
    confirmation_id = db.Column(
        db.ForeignKey("confirmation_revisions.id"), nullable=False, index=True
    )
    field_name = db.Column(db.String(60), nullable=False, index=True)
    ai_value = db.Column(db.JSON)
    human_value = db.Column(db.JSON)
    human_input = db.Column(db.JSON)
    before_value = db.Column(db.JSON)
    ai_confidence = db.Column(db.String(20), nullable=False)
    validation_warning = db.Column(db.JSON, nullable=False)
    was_corrected = db.Column(db.Boolean, nullable=False)
    correction_type = db.Column(db.String(40), nullable=False)
    correction_type_source = db.Column(db.String(20), nullable=False)
    annotation_status = db.Column(db.String(20), nullable=False)
    note = db.Column(db.Text, nullable=False, default="")


class DatasetVersion(db.Model):
    __tablename__ = "dataset_versions"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    version = db.Column(db.String(100), nullable=False, unique=True)
    category = db.Column(db.String(30), nullable=False)
    split = db.Column(db.String(20), nullable=False)
    privacy = db.Column(db.String(20), nullable=False, default="PRIVATE")
    directory = db.Column(db.Text, nullable=False)
    manifest_sha256 = db.Column(db.String(64), nullable=False)
    sample_count = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.String(40), nullable=False, default=now)


class DatasetItem(db.Model):
    __tablename__ = "dataset_items"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    dataset_id = db.Column(db.ForeignKey("dataset_versions.id"), nullable=False, index=True)
    source_job_id = db.Column(db.ForeignKey("recognition_jobs.id"), nullable=False)
    group_key = db.Column(db.String(200), nullable=False, index=True)
    image_sha256 = db.Column(db.String(64), nullable=False, index=True)
    split = db.Column(db.String(20), nullable=False)
    snapshot = db.Column(db.JSON, nullable=False)


class Benchmark(db.Model):
    __tablename__ = "benchmark_experiments"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    dataset_id = db.Column(db.ForeignKey("dataset_versions.id"), nullable=False)
    targets = db.Column(db.JSON, nullable=False)
    evaluation_version = db.Column(db.String(60), nullable=False, default="evaluation_v001")
    regression_policy = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.String(40), nullable=False, default=now)


class BenchmarkItem(db.Model):
    __tablename__ = "benchmark_items"
    id = db.Column(db.String(36), primary_key=True, default=uid)
    benchmark_id = db.Column(db.ForeignKey("benchmark_experiments.id"), nullable=False, index=True)
    dataset_item_id = db.Column(db.ForeignKey("dataset_items.id"), nullable=False)
    attempt_id = db.Column(db.ForeignKey("recognition_attempts.id"), nullable=False, unique=True)
    target_id = db.Column(db.String(100), nullable=False)
    ground_truth_snapshot = db.Column(db.JSON, nullable=False)
    field_assessments = db.Column(db.JSON, nullable=False, default=dict)
    assessment_history = db.Column(db.JSON, nullable=False, default=list)
