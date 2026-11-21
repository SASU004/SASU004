import contextlib
import io
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("GH_STATS_TOKEN", "test-token")

from scripts import update_stats


class FakeResponse:
    def __init__(self, payload, links=None, status_code=200, headers=None, text=""):
        self.payload = payload
        self.links = links or {}
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self.payload


class UpdateStatsTests(unittest.TestCase):
    def test_public_search_paginates_and_excludes_private_results(self):
        responses = [
            FakeResponse(
                {
                    "total_count": 3,
                    "incomplete_results": False,
                    "items": [
                        {
                            "sha": "public-1",
                            "repository": {"private": False},
                        },
                        {
                            "sha": "private-1",
                            "repository": {"private": True},
                        },
                    ],
                },
                links={"next": {"url": "https://api.github.com/search/commits?page=2"}},
            ),
            FakeResponse(
                {
                    "total_count": 3,
                    "incomplete_results": False,
                    "items": [
                        {
                            "sha": "public-2",
                            "repository": {"private": False},
                        },
                    ],
                }
            ),
        ]

        with patch.object(update_stats.session, "get", side_effect=responses) as get:
            self.assertEqual(
                update_stats.get_public_commit_shas(),
                {"public-1", "public-2"},
            )

        self.assertEqual(get.call_count, 2)

    def test_public_search_stops_at_github_result_window(self):
        responses = []
        for page in range(10):
            links = (
                {"next": {"url": f"https://api.github.com/search/commits?page={page + 2}"}}
                if page < 9
                else {}
            )
            responses.append(
                FakeResponse(
                    {
                        "total_count": 1_200,
                        "incomplete_results": False,
                        "items": [
                            {
                                "sha": f"commit-{page}-{index}",
                                "repository": {"private": False},
                            }
                            for index in range(100)
                        ],
                    },
                    links=links,
                )
            )

        output = io.StringIO()
        with (
            patch.object(update_stats.session, "get", side_effect=responses) as get,
            contextlib.redirect_stdout(output),
        ):
            commits = update_stats.get_public_commit_shas()

        self.assertEqual(len(commits), 1_000)
        self.assertEqual(get.call_count, 10)
        self.assertIn("only the first 1,000 can be retrieved", output.getvalue())

    def test_private_repository_commits_are_deduplicated_across_pages(self):
        responses = [
            FakeResponse(
                [{"private": True, "full_name": "secret-owner/secret-repo"}],
                links={"next": {"url": "https://api.github.com/user/repos?page=2"}},
            ),
            FakeResponse([]),
            FakeResponse(
                [{"sha": "private-1"}, {"sha": "private-1"}],
                links={
                    "next": {
                        "url": (
                            "https://api.github.com/repos/secret-owner/"
                            "secret-repo/commits?page=2"
                        )
                    }
                },
            ),
            FakeResponse([{"sha": "private-2"}]),
        ]

        with patch.object(update_stats.session, "get", side_effect=responses):
            self.assertEqual(
                update_stats.get_private_commit_shas(),
                {"private-1", "private-2"},
            )

    def test_private_api_errors_do_not_expose_repository_details(self):
        response = FakeResponse(
            {},
            status_code=404,
            text="Not found: secret-owner/secret-repo",
        )
        with patch.object(update_stats.session, "get", return_value=response):
            with self.assertRaises(RuntimeError) as raised:
                update_stats._request_json(
                    "https://api.github.com/repos/secret-owner/secret-repo/commits",
                    private=True,
                )

        self.assertNotIn("secret-owner", str(raised.exception))

    def test_rate_limit_is_reported_as_an_error(self):
        response = FakeResponse(
            {},
            status_code=403,
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "123"},
        )
        with patch.object(update_stats.session, "get", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "rate limit exceeded"):
                update_stats._request_json("https://api.github.com/search/commits")

    def test_empty_private_repository_is_counted_as_zero(self):
        response = FakeResponse({}, status_code=409)
        with patch.object(update_stats.session, "get", return_value=response):
            payload, returned_response = update_stats._request_json(
                "https://api.github.com/repos/secret-owner/empty-repo/commits",
                private=True,
                allow_empty_repository=True,
            )

        self.assertEqual(payload, [])
        self.assertIs(returned_response, response)

    def test_main_deduplicates_output_and_preserves_svg_path(self):
        with tempfile.TemporaryDirectory() as working_dir:
            output = io.StringIO()
            previous_dir = os.getcwd()
            with (
                patch.object(
                    update_stats,
                    "get_public_commit_shas",
                    return_value={"same", "public"},
                ),
                patch.object(
                    update_stats,
                    "get_private_commit_shas",
                    return_value={"same", "private-commit-sha"},
                ),
                contextlib.redirect_stdout(output),
            ):
                try:
                    os.chdir(working_dir)
                    update_stats.main()
                finally:
                    os.chdir(previous_dir)

            diagnostics = output.getvalue()
            self.assertIn("Public commits found: 2", diagnostics)
            self.assertIn("Private commits found: 1", diagnostics)
            self.assertIn("Total unique commits found: 3", diagnostics)
            with open(
                os.path.join(working_dir, "assets", "total-commits.svg"),
                encoding="utf-8",
            ) as svg_file:
                svg = svg_file.read()
            self.assertIn('fill="#282a36"', svg)
            self.assertRegex(svg, r">\s*3\s*</text>")
            self.assertNotIn("private-commit-sha", svg)


if __name__ == "__main__":
    unittest.main()
