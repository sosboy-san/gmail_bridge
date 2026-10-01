"""Exercise the actual publication policy without GitHub or Docker access."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/docker-publish.yml'


def block_after(marker, key, indentation):
    source = WORKFLOW.read_text().split(marker, 1)[1].split(key, 1)[1]
    lines = []
    for line in source.splitlines()[1:]:
        if line.strip() and not line.startswith(' ' * indentation):
            break
        lines.append(line[indentation:])
    return '\n'.join(lines)


@unittest.skipUnless(shutil.which('node'), 'Node required for actual GitHub script policy')
class ReleaseTagPolicyTest(unittest.TestCase):
    def evaluate(self, selected, existing, event='workflow_dispatch'):
        source = block_after('id: release', 'script: |', 12)
        fixture = json.dumps({'selected': selected, 'existing': existing, 'event': event})
        script = '''
const fixture = FIXTURE;
const context = {eventName: fixture.event, payload: {inputs: {tag: fixture.selected}},
 ref: 'refs/tags/' + fixture.selected, repo: {owner: 'example', repo: 'example'}};
const github = {rest: {repos: {listTags: {}}}, paginate: async () =>
 fixture.existing.map(name => ({name, commit: {sha: 'selected-sha'}}))};
const outputs = {};
const core = {setOutput: (key, value) => {outputs[key] = value;}};
(async () => { try { SOURCE; console.log(JSON.stringify(outputs)); }
 catch (error) { console.log(JSON.stringify({error: error.message})); } })();
'''.replace('FIXTURE', fixture).replace('SOURCE', source)
        result = subprocess.run(['node', '-e', script], check=True, text=True,
                                capture_output=True)
        return json.loads(result.stdout)

    def test_rc_and_stable_outputs_for_both_entrypoints(self):
        for event in ('workflow_dispatch', 'push'):
            with self.subTest(event=event):
                rc = self.evaluate('v1.1.0-rc.1', ['v1.0.0', 'v1.1.0-rc.1'], event)
                self.assertEqual(rc['rc'], 'true')
                self.assertEqual(rc['version'], '1.1.0-rc.1')
                self.assertEqual(rc['sha'], 'selected-sha')
                stable = self.evaluate('v1.1.0', ['v1.0.0', 'v1.1.0'], event)
                self.assertEqual(stable['rc'], 'false')
                self.assertEqual((stable['version'], stable['minor'], stable['major']),
                                 ('1.1.0', '1.1', '1'))

    def test_reject_invalid_missing_and_superseded_tags(self):
        invalid = ['main', 'v0.1.0', 'v1.1.0-beta.1', 'v1.1.0-rc.0',
                   'v1.1.0-rc.01', 'v01.1.0', 'v1.1.0-rc.1+build', '1.1.0']
        for tag in invalid:
            with self.subTest(tag=tag):
                self.assertIn('error', self.evaluate(tag, [tag]))
        self.assertIn('error', self.evaluate('v1.1.0-rc.1', ['v1.0.0']))
        self.assertIn('error', self.evaluate('v1.0.0', ['v1.0.0', 'v1.1.0']))
        for stable in ('v1.1.0', 'v1.2.0', 'v2.0.0'):
            with self.subTest(stable=stable):
                self.assertIn('error', self.evaluate('v1.1.0-rc.1',
                                                    ['v1.1.0-rc.1', stable]))


class DistributionTagsTest(unittest.TestCase):
    def test_rc_exact_only_and_stable_four_tags(self):
        script = block_after('id: distribution', 'run: |', 10)
        for rc, expected in (
            ('true', ['sosboy/gmail-bridge:1.1.0-rc.1']),
            ('false', ['sosboy/gmail-bridge:1.1.0', 'sosboy/gmail-bridge:1.1',
                       'sosboy/gmail-bridge:1', 'sosboy/gmail-bridge:latest']),
        ):
            with self.subTest(rc=rc), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / 'output'
                subprocess.run(['bash', '-eu', '-c', script], check=True,
                               env={**os.environ, 'IMAGE': 'sosboy/gmail-bridge',
                                    'VERSION': '1.1.0-rc.1' if rc == 'true' else '1.1.0',
                                    'RC': rc, 'MINOR': '1.1', 'MAJOR': '1',
                                    'GITHUB_OUTPUT': str(output)})
                tags = output.read_text().splitlines()[1:-1]
                self.assertEqual(tags, expected)
        source = WORKFLOW.read_text()
        self.assertIn('tags: ${{ steps.distribution.outputs.tags }}', source)
        # Guard that verification uses the same stable-only branch.
        self.assertRegex(source, re.compile(
            r'Verify all tags.*if \[\[ "\$RC" == false \]\]; then', re.S))


if __name__ == '__main__':
    unittest.main()
