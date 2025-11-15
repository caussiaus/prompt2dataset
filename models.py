"""
Data models for AI-Augmented Web Scraper
"""
from pydantic import BaseModel, HttpUrl, Field
from typing import List, Optional, Dict, Any, Literal
from datetime import datetime
from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentType(str, Enum):
    DISCOVERY = "discovery"
    EXTRACTION = "extraction"
    VISION = "vision"
    CAMOUFOX = "camoufox"


class ScrapingTask(BaseModel):
    """Scraping task configuration"""
    task_id: str = Field(default_factory=lambda: str(datetime.utcnow().timestamp()))
    url: str
    scraping_type: Literal["discovery", "extraction", "vision", "full"] = "full"
    extract_images: bool = True
    extract_text: bool = True
    extract_links: bool = True
    use_browser: bool = False
    javascript_enabled: bool = False
    wait_for_selector: Optional[str] = None
    pagination: bool = False
    max_depth: int = 1
    follow_links: bool = False
    css_selectors: Optional[Dict[str, str]] = None
    llm_extraction_prompt: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ScrapingResult(BaseModel):
    """Scraping result data"""
    task_id: str
    url: str
    status: TaskStatus
    data: Dict[str, Any] = Field(default_factory=dict)
    raw_html: Optional[str] = None
    text_content: Optional[str] = None
    extracted_data: Optional[Dict[str, Any]] = None
    images: List[Dict[str, Any]] = Field(default_factory=list)
    links: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    processing_time: Optional[float] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class DiscoveryRequest(BaseModel):
    """Discovery agent request"""
    url: str
    max_depth: int = 1
    follow_links: bool = False
    extract_links: bool = True
    filters: Optional[Dict[str, Any]] = None


class DiscoveryResponse(BaseModel):
    """Discovery agent response"""
    url: str
    discovered_urls: List[str] = Field(default_factory=list)
    site_structure: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExtractionRequest(BaseModel):
    """Extraction agent request"""
    url: Optional[str] = None
    html_content: Optional[str] = None
    css_selectors: Optional[Dict[str, str]] = None
    extraction_schema: Optional[Dict[str, Any]] = None
    llm_prompt: Optional[str] = None
    use_llm: bool = True


class ExtractionResponse(BaseModel):
    """Extraction agent response"""
    extracted_data: Dict[str, Any]
    structured_data: Optional[List[Dict[str, Any]]] = None
    summary: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class VisionRequest(BaseModel):
    """Vision agent request"""
    image_urls: List[str] = Field(default_factory=list)
    image_data: Optional[List[bytes]] = None
    task_type: Literal["ocr", "vqa", "description", "classification"] = "description"
    question: Optional[str] = None
    model: Optional[str] = None


class VisionResponse(BaseModel):
    """Vision agent response"""
    results: List[Dict[str, Any]]
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ModelInfo(BaseModel):
    """Model information"""
    name: str
    type: Literal["vision", "llm", "embedding", "code", "rag"]
    size: Optional[str] = None
    status: Literal["available", "downloading", "not_available"] = "not_available"
    source: Literal["ollama", "huggingface"] = "ollama"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ModelDownloadRequest(BaseModel):
    """Model download request"""
    models: List[str]
    source: Literal["ollama", "huggingface"] = "ollama"
    force: bool = False


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    agent: str
    version: str = "1.0.0"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    dependencies: Dict[str, bool] = Field(default_factory=dict)
