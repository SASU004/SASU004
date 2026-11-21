"""Generate a Dracula-themed card from public search and accessible private commits.

GitHub commit search only indexes commits on repository default branches and
returns at most 1,000 results. The resulting total is therefore not a guaranteed
lifetime count.
"""

import os
from urllib.parse import quote

import requests

TOKEN = os.environ["GH_STATS_TOKEN"]
USERNAME = "SASU004"
API_URL = "https://api.github.com"
SEARCH_RESULT_LIMIT = 1_000
PER_PAGE = 100

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

session = requests.Session()
session.headers.update(HEADERS)


def _request_json(url, params=None, *, private=False, allow_empty_repository=False):
    context = "counting private commits" if private else "searching public commits"

    try:
        response = session.get(url, params=params)
    except requests.RequestException:
        raise RuntimeError(f"GitHub API request failed while {context}.") from None

    if response.status_code == 409 and allow_empty_repository:
        return [], response

    if response.status_code >= 400:
        remaining = response.headers.get("X-RateLimit-Remaining")
        is_rate_limited = response.status_code == 429 or (
            response.status_code == 403
            and (
                remaining == "0"
                or "Retry-After" in response.headers
                or "rate limit" in response.text.lower()
            )
        )
        if is_rate_limited:
            reset = response.headers.get("X-RateLimit-Reset")
            suffix = f" Rate limit resets at Unix time {reset}." if reset else ""
            raise RuntimeError(f"GitHub API rate limit exceeded while {context}.{suffix}")
        raise RuntimeError(
            f"GitHub API returned HTTP {response.status_code} while {context}."
        )

    try:
        return response.json(), response
    except ValueError:
        raise RuntimeError(f"GitHub API returned invalid JSON while {context}.") from None


def _items(payload, *, private=False):
    if not isinstance(payload, list):
        context = "private repository" if private else "repository"
        raise RuntimeError(f"GitHub API returned an invalid {context} list.")
    return payload


def get_public_commit_shas():
    url = f"{API_URL}/search/commits"
    params = {
        "q": f"author:{USERNAME}",
        "per_page": PER_PAGE,
        "page": 1,
    }
    payload, response = _request_json(url, params=params)
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise RuntimeError("GitHub commit search returned an invalid response.")
    total_count = payload.get("total_count")
    if not isinstance(total_count, int) or total_count < 0:
        raise RuntimeError("GitHub commit search returned an invalid result count.")

    commit_shas = set()
    results_seen = 0
    incomplete_results = payload.get("incomplete_results") is True
    result_limit = min(total_count, SEARCH_RESULT_LIMIT)

    while True:
        items = payload["items"]
        results_seen += len(items)
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("sha"), str):
                raise RuntimeError("GitHub commit search returned an invalid commit.")
            repository = item.get("repository")
            if not isinstance(repository, dict) or not isinstance(
                repository.get("private"), bool
            ):
                raise RuntimeError("GitHub commit search returned invalid repository visibility.")
            if repository["private"]:
                continue
            commit_shas.add(item["sha"])

        next_url = response.links.get("next", {}).get("url")
        if (
            not next_url
            or results_seen >= result_limit
            or results_seen >= SEARCH_RESULT_LIMIT
        ):
            break
        payload, response = _request_json(next_url)
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise RuntimeError("GitHub commit search returned an invalid response.")
        incomplete_results = incomplete_results or payload.get("incomplete_results") is True

    if total_count > SEARCH_RESULT_LIMIT:
        print(
            "Warning: GitHub commit search matched more than 1,000 results; "
            "only the first 1,000 can be retrieved, so the public count may be incomplete."
        )
    if incomplete_results:
        print("Warning: GitHub reported incomplete public commit search results.")

    return commit_shas


def get_all_private_repositories():
    url = f"{API_URL}/user/repos"
    params = {
        "visibility": "private",
        "affiliation": "owner,collaborator,organization_member",
        "per_page": PER_PAGE,
    }
    repositories = []

    while url:
        payload, response = _request_json(url, params=params, private=True)
        page_repositories = _items(payload, private=True)
        for repository in page_repositories:
            if (
                not isinstance(repository, dict)
                or not isinstance(repository.get("private"), bool)
            ):
                raise RuntimeError(
                    "GitHub returned an invalid private repository while counting commits."
                )
            if repository["private"]:
                repositories.append(repository)
        url = response.links.get("next", {}).get("url")
        params = None

    return repositories


def get_private_commit_shas():
    commit_shas = set()
    repositories = get_all_private_repositories()

    for repository in repositories:
        full_name = repository.get("full_name")
        if not isinstance(full_name, str):
            raise RuntimeError(
                "GitHub returned an invalid private repository while counting commits."
            )

        url = f"{API_URL}/repos/{quote(full_name, safe='/')}/commits"
        params = {
            "author": USERNAME,
            "per_page": PER_PAGE,
        }

        while url:
            payload, response = _request_json(
                url,
                params=params,
                private=True,
                allow_empty_repository=True,
            )
            for commit in _items(payload, private=True):
                if not isinstance(commit, dict) or not isinstance(
                    commit.get("sha"), str
                ):
                    raise RuntimeError(
                        "GitHub returned an invalid private commit while counting commits."
                    )
                commit_shas.add(commit["sha"])
            url = response.links.get("next", {}).get("url")
            params = None

    return commit_shas


def main():
    public_commit_shas = get_public_commit_shas()
    private_commit_shas = get_private_commit_shas()
    private_only_shas = private_commit_shas - public_commit_shas
    total_commit_count = len(public_commit_shas | private_commit_shas)

    print(f"Public commits found: {len(public_commit_shas)}")
    print(f"Private commits found: {len(private_only_shas)}")
    print(f"Total unique commits found: {total_commit_count}")
    print(
        "Scope: public results cover commits indexed on default branches and "
        "are limited to 1,000 search results; this is not a guaranteed lifetime count."
    )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg"
    width="400" height="150" viewBox="0 0 400 150">
      <rect width="400" height="150" rx="12"
      fill="#282a36" stroke="#6272a4"/>
      <text x="25" y="40" fill="#bd93f9"
      font-size="17" font-family="Arial">
        TOTAL COMMITS
      </text>
      <text x="25" y="100" fill="#f8f8f2"
      font-size="43" font-weight="bold"
      font-family="Arial">
        {total_commit_count:,}
      </text>
      <text x="25" y="128" fill="#8be9fd"
      font-size="12" font-family="Arial">
        SASU004 · PUBLIC + PRIVATE
      </text>
    </svg>"""

    os.makedirs("assets", exist_ok=True)

    with open("assets/total-commits.svg", "w", encoding="utf-8") as file:
        file.write(svg)


if __name__ == "__main__":
    main()
