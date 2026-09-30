import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from github import Github, GithubException

from pr_review.models import Comment, FileChange, PRContext, PullRequestSummary, Review


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
                "body": _format_comment_body(c),
            }
            for c in review.comments
        ]
        body = review.summary if review.comments else "LGTM! _—El + Claude PR review bot_"
        created = pr.create_review(
            commit=repo.get_commit(summary.head_sha),
            body=body,
            comments=comments,
        )
        return created.id


def _format_comment_body(c: Comment) -> str:
    prefix = "**[bug]**" if c.severity == "bug" else "**[question]**"
    body = f"{prefix} {c.body}\n\n_Evidence:_ `{c.evidence.citation}`"
    if c.evidence.quoted_code:
        body += f"\n\n```\n{c.evidence.quoted_code}\n```"
    body += "\n\n_—El + Claude PR review bot_"
    return body
