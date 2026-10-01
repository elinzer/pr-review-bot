import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from github import Github, GithubException

from pr_review.models import Comment, FileChange, PRContext, PullRequestSummary, Review, ReviewSnapshot, SubmittedComment


SIGNATURE = "_—El + Claude PR review bot_"
LGTM_BODY = f"LGTM! {SIGNATURE}"


@dataclass
class GitHubClient:
    github: Github
    team_slug: str
    max_age_days: int = 14

    @classmethod
    def from_pat(cls, pat: str, team_slug: str, max_age_days: int = 14) -> "GitHubClient":
        return cls(github=Github(pat), team_slug=team_slug, max_age_days=max_age_days)

    def list_team_review_requests(self) -> list[PullRequestSummary]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.max_age_days)).strftime("%Y-%m-%d")
        query = (
            f"is:pr is:open -is:draft "
            f"team-review-requested:{self.team_slug} "
            f"created:>={cutoff}"
        )
        try:
            results = list(self.github.search_issues(query))
        except GithubException as e:
            if e.status != 404 and e.status < 500:
                raise
            time.sleep(5)
            results = list(self.github.search_issues(query))
        out = []
        for issue in results:
            pr = issue.as_pull_request()
            out.append(PullRequestSummary(
                url=issue.html_url,
                repo_full_name=issue.repository.full_name,
                number=issue.number,
                title=issue.title,
                head_sha=pr.head.sha,
                body=pr.body or "",
                branch=pr.head.ref,
            ))
        return out

    def get_pr_context(self, summary: PullRequestSummary) -> PRContext:
        repo = self.github.get_repo(summary.repo_full_name)
        pr = repo.get_pull(summary.number)
        files = []
        other_changes = []
        for f in pr.get_files():
            renamed = f.status == "renamed"
            if not f.patch:
                if renamed:
                    other_changes.append(f"renamed: {f.previous_filename} -> {f.filename} (no content change)")
                else:
                    other_changes.append(f"{f.status}: {f.filename} (no diff shown: binary or too large)")
                continue
            files.append(FileChange(
                path=f.filename,
                patch=f.patch,
                additions=f.additions,
                deletions=f.deletions,
                previous_path=f.previous_filename if renamed else "",
            ))
        return PRContext(summary=summary, files=files, other_changes=other_changes)

    def create_pending_review(self, summary: PullRequestSummary, review: Review) -> int:
        repo = self.github.get_repo(summary.repo_full_name)
        pr = repo.get_pull(summary.number)
        comments = [
            {
                "path": c.file,
                "line": c.line,
                "side": "RIGHT",
                "body": format_comment_body(c),
            }
            for c in review.comments
        ]
        body = review_body(review)
        created = pr.create_review(
            commit=repo.get_commit(summary.head_sha),
            body=body,
            comments=comments,
        )
        return created.id

    def get_review(self, repo_full_name: str, number: int, review_id: int) -> Optional[ReviewSnapshot]:
        pr = self.github.get_repo(repo_full_name).get_pull(number)
        try:
            r = pr.get_review(review_id)
        except GithubException as e:
            if e.status == 404:
                return None
            raise
        return ReviewSnapshot(
            state=r.state,
            body=r.body or "",
            submitted_at=r.submitted_at.isoformat() if r.submitted_at else None,
        )

    def get_pr_status(self, repo_full_name: str, number: int) -> str:
        pr = self.github.get_repo(repo_full_name).get_pull(number)
        if pr.merged:
            return "merged"
        return pr.state

    def get_review_comments(self, repo_full_name: str, number: int, review_id: int) -> list[SubmittedComment]:
        pr = self.github.get_repo(repo_full_name).get_pull(number)
        return [
            SubmittedComment(
                path=c.path,
                line=c.original_line if c.original_line is not None else c.line,
                body=c.body or "",
            )
            for c in pr.get_single_review_comments(review_id)
        ]


def review_body(review: Review) -> str:
    return review.summary if review.comments else LGTM_BODY


def format_comment_body(c: Comment) -> str:
    prefix = "**[bug]**" if c.severity == "bug" else "**[question]**"
    body = f"{prefix} {c.body}\n\n_Evidence:_ `{c.evidence.citation}`"
    if c.evidence.quoted_code:
        body += f"\n\n```\n{c.evidence.quoted_code}\n```"
    body += f"\n\n{SIGNATURE}"
    return body
