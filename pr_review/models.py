from dataclasses import dataclass, field
from typing import Literal, Optional


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
    previous_path: str = ""


@dataclass(frozen=True)
class DiscussionComment:
    author: str
    body: str
    created_at: str
    path: Optional[str] = None
    line: Optional[int] = None
    outdated: bool = False


@dataclass(frozen=True)
class PRContext:
    summary: PullRequestSummary
    files: list[FileChange]
    other_changes: list[str] = field(default_factory=list)
    discussion: list[DiscussionComment] = field(default_factory=list)

    @property
    def changed_file_paths(self) -> set[str]:
        return {f.path for f in self.files}


@dataclass(frozen=True)
class JiraContext:
    key: str
    title: str
    description: str
    epic: str = ""
    linked_issues: list[str] = field(default_factory=list)


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


@dataclass(frozen=True)
class ReviewSnapshot:
    state: str
    body: str
    submitted_at: Optional[str]


@dataclass(frozen=True)
class SubmittedComment:
    path: str
    line: Optional[int]
    body: str
