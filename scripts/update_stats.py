import os
import requests
import re

TOKEN = os.environ["GH_STATS_TOKEN"]
USERNAME = "SASU004"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28"
}

session = requests.Session()
session.headers.update(HEADERS)


def get_all_repositories():
    repos = []
    url = "https://api.github.com/user/repos"

    params = {
        "visibility": "all",
        "affiliation": "owner",
        "per_page": 100
    }

    while url:
        response = session.get(url, params=params)
        response.raise_for_status()
        repos.extend(response.json())
        url = response.links.get("next", {}).get("url")
        params = None

    return repos


def count_commits(repo):
    url = (
        f"https://api.github.com/repos/"
        f"{repo['full_name']}/commits"
    )

    response = session.get(
        url,
        params={"author": USERNAME, "per_page": 1}
    )

    if response.status_code == 409:
        return 0

    response.raise_for_status()

    commits = response.json()

    if not commits:
        return 0

    last_page = response.links.get("last", {}).get("url")

    if last_page:
        match = re.search(r"[?&]page=(\d+)", last_page)
        if match:
            return int(match.group(1))

    return len(commits)


def main():
    repositories = get_all_repositories()

    total_commits = 0

    for repo in repositories:
        count = count_commits(repo)
        total_commits += count

    print(f"Repositories checked: {len(repositories)}")
    print(f"Total commits: {total_commits}")

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
        {total_commits:,}
      </text>
      <text x="25" y="128" fill="#8be9fd"
      font-size="12" font-family="Arial">
        SASU004 · PUBLIC + PRIVATE
      </text>
    </svg>"""

    os.makedirs("assets", exist_ok=True)

    with open("assets/total-commits.svg", "w") as file:
        file.write(svg)


if __name__ == "__main__":
    main()