"""Central configuration. Every path is relative to the project root; override with env vars (prefix RFP_) or `.env`."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]

TENDERS_WS = "tenders"
KB_WS = "knowledge-base"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(PROJECT_ROOT / ".env"), env_prefix="RFP_", extra="ignore")

    data_dir: Path = PROJECT_ROOT / "data" / "runtime"

    # Providers: "ollama" (default, local) or "fake" (deterministic, used by unit tests)
    llm_provider: str = "ollama"
    embed_provider: str = "ollama"
    rerank_provider: str = "cross-encoder"  # cross-encoder | overlap (tests)
    rerank_device: str = "auto"  # auto | cuda | cpu

    ollama_url: str = "http://localhost:11434"
    llm_model: str = "qwen2.5:7b"
    embed_model: str = "nomic-embed-text"
    reranker_model: str = "BAAI/bge-reranker-base"
    llm_num_ctx: int = 8192
    llm_temperature: float = 0.1

    # Retrieval
    retrieval_mode: str = "hybrid"  # bm25 | vector | hybrid
    use_reranker: bool = True
    candidates: int = 20  # per retriever before fusion
    top_k: int = 5  # chunks passed to the LLM
    rrf_k: int = 60
    not_found_threshold: float = 0.02

    # Chunking
    chunk_chars: int = 1100
    chunk_overlap_chars: int = 150

    # RFP analysis
    req_batch_chars: int = 3600  # RFP text per requirement-extraction LLM call
    kb_evidence_k: int = 4  # knowledge-base chunks used to judge each requirement

    cors_origins: str = "http://localhost:3200,http://127.0.0.1:3200"
    release: str = "v1.0.0"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "rfp.db"

    @property
    def qdrant_path(self) -> Path:
        return self.data_dir / "qdrant"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def export_dir(self) -> Path:
        return self.data_dir / "exports"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    for d in (s.data_dir, s.upload_dir, s.export_dir):
        d.mkdir(parents=True, exist_ok=True)
    return s
