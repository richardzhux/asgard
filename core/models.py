from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any


@dataclass
class TextChunk:
    text: str
    start_unit: int
    end_unit: int
    idx: int


@dataclass
class Document:
    path: Path
    title: str
    chunks: List[TextChunk]
    total_units: int
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentConfig:
    agent_id: str
    name: str
    brief: str
    focus: str
    style: str
    model: str
    reasoning: Optional[str] = None
    text_verbosity: Optional[str] = None


@dataclass
class AgentReport:
    agent: AgentConfig
    document: Document
    memo_text: str
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class AgentTestimony:
    agent: AgentConfig
    summary: str
    verdict_score: int
    confidence: str
    supporting_points: List[str]
    concerns: List[str]
    recommended_actions: List[str]
    citations: List[str]
    doctrinal_refs: List[str] = field(default_factory=list)
    example_passages: List[str] = field(default_factory=list)
    usage_role: str = "background"
    importance_within_cluster: int = 3

    def to_dict(self) -> Dict[str, object]:
        return {
            "agent_id": self.agent.agent_id,
            "agent_name": self.agent.name,
            "model": self.agent.model,
            "verdict_score": self.verdict_score,
            "confidence": self.confidence,
            "summary": self.summary,
            "supporting_points": self.supporting_points,
            "concerns": self.concerns,
            "recommended_actions": self.recommended_actions,
            "citations": self.citations,
            "doctrinal_refs": self.doctrinal_refs,
            "example_passages": self.example_passages,
            "usage_role": self.usage_role,
            "importance_within_cluster": self.importance_within_cluster,
        }


@dataclass
class ClaimEvaluation:
    claim_analysis: str
    scholarly_consensus_label: str
    scholarly_consensus_pct: float
    supporting_evidence: List[str]
    counterarguments: List[str]
    conclusion: str
    recommendations: List[str]
    overall_perspective: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "claim_analysis": self.claim_analysis,
            "scholarly_consensus_label": self.scholarly_consensus_label,
            "scholarly_consensus_pct": self.scholarly_consensus_pct,
            "supporting_evidence": self.supporting_evidence,
            "counterarguments": self.counterarguments,
            "conclusion": self.conclusion,
            "recommendations": self.recommendations,
            "overall_perspective": self.overall_perspective,
        }


@dataclass
class JudgeDecision:
    document_title: str
    final_vote: str
    confidence: str
    majority_rationale: str
    dissenting_points: List[str]
    consensus_points: List[str]
    disagreements: List[Dict[str, object]]
    unresolved_questions: List[str]
    agent_votes: Dict[str, Dict[str, object]]
    doctrinal_refs: List[str] = field(default_factory=list)
    example_passages: List[str] = field(default_factory=list)
    usage_role: str = "background"
    importance_within_cluster: int = 3
    summary: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "document_title": self.document_title,
            "final_vote": self.final_vote,
            "confidence": self.confidence,
            "majority_rationale": self.majority_rationale,
            "dissenting_points": self.dissenting_points,
            "consensus_points": self.consensus_points,
            "disagreements": self.disagreements,
            "unresolved_questions": self.unresolved_questions,
            "agent_votes": self.agent_votes,
            "doctrinal_refs": self.doctrinal_refs,
            "example_passages": self.example_passages,
            "usage_role": self.usage_role,
            "importance_within_cluster": self.importance_within_cluster,
            "summary": self.summary,
        }
