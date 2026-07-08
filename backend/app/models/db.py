"""数据库模型 — SQLAlchemy ORM"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, JSON, Text, ForeignKey, create_engine
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


def gen_id() -> str:
    return uuid.uuid4().hex[:16]


class LearnerModel(Base):
    __tablename__ = "learners"

    learner_id = Column(String(64), primary_key=True, default=gen_id)
    name = Column(String(128), nullable=False)
    education = Column(JSON, default=dict)
    experience = Column(JSON, default=dict)
    knowledge_map = Column(JSON, default=dict)
    skill_gaps = Column(JSON, default=list)
    learning_style = Column(String(32))
    recommended_difficulty = Column(String(16))
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ResourceModel(Base):
    __tablename__ = "resources"

    resource_id = Column(String(64), primary_key=True, default=gen_id)
    learner_id = Column(String(64), ForeignKey("learners.learner_id"))
    resource_type = Column(String(32), nullable=False)
    title = Column(String(256))
    content = Column(Text)
    citations = Column(JSON, default=list)
    difficulty_level = Column(String(16))
    target_skill_gaps = Column(JSON, default=list)
    estimated_duration_minutes = Column(Integer, default=30)
    is_approved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)


class AuditLogModel(Base):
    __tablename__ = "audit_logs"

    audit_id = Column(String(64), primary_key=True, default=gen_id)
    resource_id = Column(String(64), ForeignKey("resources.resource_id"))
    verdict = Column(String(32))
    fact_check = Column(JSON, default=dict)
    compliance_check = Column(JSON, default=dict)
    difficulty_match = Column(JSON, default=dict)
    knowledge_coverage = Column(Float, default=0.0)
    hallucination_flags = Column(JSON, default=list)
    confidence_score = Column(Float, default=0.0)
    reviewed_at = Column(DateTime, default=datetime.now)


class InteractionModel(Base):
    __tablename__ = "interactions"

    interaction_id = Column(String(64), primary_key=True, default=gen_id)
    learner_id = Column(String(64), ForeignKey("learners.learner_id"))
    resource_id = Column(String(64), ForeignKey("resources.resource_id"))
    quiz_submission = Column(JSON, default=dict)
    quiz_result = Column(JSON, default=dict)
    feedback_action = Column(String(32))
    created_at = Column(DateTime, default=datetime.now)


class DomainDocModel(Base):
    __tablename__ = "domain_docs"

    doc_id = Column(String(64), primary_key=True, default=gen_id)
    domain = Column(String(128))
    title = Column(String(256))
    file_type = Column(String(16))
    original_path = Column(Text)
    chunk_count = Column(Integer, default=0)
    indexed_in_milvus = Column(Boolean, default=False)
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.now)


def init_db(database_url: str = None):
    """初始化数据库"""
    from ..core.config import settings
    url = database_url or settings.DATABASE_URL
    engine = create_engine(url.replace("+asyncpg", "").replace("+aiosqlite", ""))
    Base.metadata.create_all(engine)
    return engine
