import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lxml import etree

os.environ.setdefault('ACCESS_TOKEN', 'test-token')
os.environ.setdefault('USER_NAME', 'test-user')

import today


class FakeResponse:
    def __init__(self, payload, status_code=200, text=''):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload


class GitHubRequestTests(unittest.TestCase):
    @mock.patch('today.time.sleep')
    @mock.patch('today.requests.post')
    def test_retries_transient_server_error(self, post, sleep):
        post.side_effect = [
            FakeResponse({}, status_code=502, text='Bad Gateway'),
            FakeResponse({'data': {'viewer': {'login': 'test-user'}}}),
        ]

        response = today.github_request('test_query', 'query { viewer { login } }', {})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(1)

    @mock.patch('today.simple_request')
    def test_star_count_uses_all_repository_pages(self, request):
        request.side_effect = [
            FakeResponse({
                'data': {
                    'user': {
                        'repositories': {
                            'totalCount': 2,
                            'edges': [
                                {'node': {'stargazers': {'totalCount': 2}}},
                            ],
                            'pageInfo': {
                                'hasNextPage': True,
                                'endCursor': 'next-page',
                            },
                        },
                    },
                },
            }),
            FakeResponse({
                'data': {
                    'user': {
                        'repositories': {
                            'totalCount': 2,
                            'edges': [
                                {'node': {'stargazers': {'totalCount': 3}}},
                            ],
                            'pageInfo': {
                                'hasNextPage': False,
                                'endCursor': None,
                            },
                        },
                    },
                },
            }),
        ]

        stars = today.graph_repos_stars('stars', ['OWNER'])

        self.assertEqual(stars, 5)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(
            request.call_args_list[1].args[2]['cursor'],
            'next-page',
        )


class SvgOverwriteTests(unittest.TestCase):
    def test_core_stats_update_when_loc_is_unavailable(self):
        svg = '''\
<svg xmlns="http://www.w3.org/2000/svg">
  <text>
    <tspan id="age_data_dots">...</tspan><tspan id="age_data">waiting</tspan>
    <tspan id="star_data_dots">...</tspan><tspan id="star_data">0</tspan>
    <tspan id="repo_data_dots">...</tspan><tspan id="repo_data">0</tspan>
    <tspan id="contrib_data">0</tspan>
    <tspan id="follower_data_dots">...</tspan><tspan id="follower_data">0</tspan>
    <tspan id="commit_data_dots">...</tspan><tspan id="commit_data">old</tspan>
    <tspan id="loc_data_dots">...</tspan><tspan id="loc_data">old</tspan>
  </text>
</svg>
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profile.svg'
            path.write_text(svg, encoding='utf-8')

            today.svg_overwrite(
                path,
                '1 year',
                None,
                5,
                22,
                24,
                7,
                None,
            )

            root = etree.parse(path).getroot()
            self.assertEqual(root.find(".//*[@id='age_data']").text, '1 year')
            self.assertEqual(root.find(".//*[@id='star_data']").text, '5')
            self.assertEqual(root.find(".//*[@id='repo_data']").text, '22')
            self.assertEqual(root.find(".//*[@id='contrib_data']").text, '24')
            self.assertEqual(root.find(".//*[@id='follower_data']").text, '7')
            self.assertEqual(root.find(".//*[@id='commit_data']").text, 'old')
            self.assertEqual(root.find(".//*[@id='loc_data']").text, 'old')


class CacheBuilderTests(unittest.TestCase):
    def test_cache_rows_follow_repository_identity_not_api_order(self):
        first_hash = hashlib.sha256(b'owner/first').hexdigest()
        second_hash = hashlib.sha256(b'owner/second').hexdigest()
        edges = [
            {
                'node': {
                    'nameWithOwner': 'owner/second',
                    'defaultBranchRef': {
                        'target': {'history': {'totalCount': 20}},
                    },
                },
            },
            {
                'node': {
                    'nameWithOwner': 'owner/first',
                    'defaultBranchRef': {
                        'target': {'history': {'totalCount': 10}},
                    },
                },
            },
        ]

        with tempfile.TemporaryDirectory() as directory:
            cache_dir = Path(directory) / 'cache'
            cache_dir.mkdir()
            cache_file = cache_dir / (
                hashlib.sha256(b'test-user').hexdigest() + '.txt'
            )
            cache_file.write_text(
                f'{first_hash} 10 1 100 25\n'
                f'{second_hash} 20 2 200 50\n',
                encoding='utf-8',
            )
            previous_directory = os.getcwd()
            os.chdir(directory)
            try:
                with mock.patch.object(today, 'USER_NAME', 'test-user'):
                    result = today.cache_builder(edges, 0, False)
            finally:
                os.chdir(previous_directory)

            self.assertEqual(result, [300, 75, 225, True])
            self.assertEqual(
                cache_file.read_text(encoding='utf-8').splitlines(),
                [
                    f'{second_hash} 20 2 200 50',
                    f'{first_hash} 10 1 100 25',
                ],
            )


if __name__ == '__main__':
    unittest.main()
