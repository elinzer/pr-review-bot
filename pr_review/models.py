from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class PullRequestSummary:
    url: str
    repo_full_name: str
    number: int
    title: str
    head_sha: str
    body: str
    branch: str


@dataclass(frozen=True)
class FileChange:
    path: str
    patch: str
    additions: int
    deletions: int


@dataclass(frozen=True)
class PRContext:
    summary: PullRequestSummary
    files: list[FileChange]

    @property
    def changed_file_paths(self) -> set[str]:
        return {f.path for f in self.files}


@dataclass(frozen=True)
class JiraContext:
    key: str
    title: str
    description: str
    acceptance_criteria: str


@dataclass(frozen=True)
class Evidence:
    quoted_code: str
    citation: str


Severity = Literal["bug", "question"]


@dataclass(frozen=True)
class Comment:
    file: str
    line: int
    severity: Severity
    body: str
    evidence: Evidence


@dataclass(frozen=True)
class Review:
    summary: str
    comments: list[Comment] = field(default_factory=list)
