from dataclasses import dataclass

from github import Github

from pr_review.models import Comment, FileChange, PRContext, PullRequestSummary, Review


@dataclass
class GitHubClient:
    github: Github
    team_slug: str

    @classmethod
    def from_pat(cls, pat: str, team_slug: str) -> "GitHubClient":
        return cls(github=Github(pat), team_slug=team_slug)

    def list_team_review_requests(self) -> list[PullRequestSummary]:
        query = f"is:pr is:open review-requested:{self.team_slug}"
        results = self.github.search_issues(query)
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
        for f in pr.get_files():
            if not f.patch:
                continue
            files.append(FileChange(
                path=f.filename,
                patch=f.patch,
                additions=f.additions,
                deletions=f.deletions,
            ))
        return PRContext(summary=summary, files=files)

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
        created = pr.create_review(
            commit=repo.get_commit(summary.head_sha),
            body=review.summary,
            comments=comments,
        )
        return created.id


def _format_comment_body(c: Comment) -> str:
    prefix = "**[bug]**" if c.severity == "bug" else "**[question]**"
    body = f"{prefix} {c.body}\n\n_Evidence:_ `{c.evidence.citation}`"
    if c.evidence.quoted_code:
        body += f"\n\n```\n{c.evidence.quoted_code}\n```"
    return body
