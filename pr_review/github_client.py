from dataclasses import dataclass

from github import Github

from pr_review.models import FileChange, PRContext, PullRequestSummary


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
