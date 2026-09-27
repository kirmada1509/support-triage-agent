"""Small Linear GraphQL adapter; every response is checked before an issue is reported created."""

from dataclasses import dataclass

import httpx

from app.settings import settings

TEAMS = "query Teams { teams { nodes { id key name } } }"
CREATE = """mutation CreateIssue($input: IssueCreateInput!) {
  issueCreate(input: $input) { success issue { id identifier url } }
}"""


@dataclass(frozen=True)
class Issue:
    identifier: str
    url: str


async def _graphql(client: httpx.AsyncClient, key: str, query: str, variables=None) -> dict:
    response = await client.post(
        settings.linear_api_url,
        headers={"Authorization": key},
        json={"query": query, "variables": variables or {}},
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors") or not isinstance(payload.get("data"), dict):
        raise ValueError(f"Linear GraphQL error: {payload.get('errors', 'missing data')}")
    return payload["data"]


async def create_issue(
    key: str,
    team_key: str,
    title: str,
    description: str,
    priority: int,
    client: httpx.AsyncClient | None = None,
) -> Issue:
    if client is None:
        async with httpx.AsyncClient(timeout=20) as owned:
            return await create_issue(key, team_key, title, description, priority, owned)
    teams = (await _graphql(client, key, TEAMS))["teams"]["nodes"]
    team = next((t for t in teams if t["key"] == team_key), None)
    if team is None:
        raise ValueError(f"Linear team {team_key!r} is not in this workspace")
    result = (
        await _graphql(
            client,
            key,
            CREATE,
            {
                "input": {
                    "teamId": team["id"],
                    "title": title,
                    "description": description,
                    "priority": priority,
                }
            },
        )
    )["issueCreate"]
    if not result or not result.get("success") or not result.get("issue"):
        raise ValueError("Linear did not create the issue")
    issue = result["issue"]
    if not issue.get("identifier") or not issue.get("url"):
        raise ValueError("Linear created an issue without an identifier or URL")
    return Issue(identifier=issue["identifier"], url=issue["url"])
