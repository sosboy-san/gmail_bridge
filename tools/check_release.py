"""Inspect the explicit public file set without printing possible secret values.

This is a heuristic check, not a substitute for owner review or history scanning.
Optional --archive writes a ZIP containing only this same public file set.
"""

import argparse
import ast
import configparser
import hashlib
import json
import re
import zipfile
from pathlib import Path
from string import Formatter

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = (
    '.gitignore', '.dockerignore', '.gitattributes', 'Dockerfile',
    'docker-compose.example.yml', 'docker-compose.image.example.yml', 'DOCKER_RELEASE.md', 'config.example.ini', 'requirements.txt',
    'requirements-dev.txt', 'pyproject.toml', 'make_token.py', 'LICENSE',
    'README.md', 'INSTALL.md', 'UNINSTALL.md', 'TROUBLESHOOTING.md',
    'CONTRIBUTING.md', 'SECURITY.md', 'RELEASE_NOTES.md',
)


def public_files():
    paths = [ROOT / name for name in ROOT_FILES]
    paths.extend(ROOT / 'docs' / name for name in (
        'index.html', 'privacy.html', 'terms.html', 'style.css',
        '.nojekyll', 'PUBLISHING.md',
    ))
    for directory, pattern in (('app', '*.py'), ('app/locales', '*.json'),
                               ('tests', '*.py'), ('tools', '*.py'),
                               ('.github/workflows', '*.yml')):
        paths.extend(sorted((ROOT / directory).glob(pattern)))
    return sorted(paths)


def inspect():
    findings = []
    patterns = {
        'Google access token': re.compile(r'ya29\.[A-Za-z0-9_-]{15,}'),
        'Google client secret': re.compile(r'GOCSPX-[A-Za-z0-9_-]{12,}'),
        'Google API key': re.compile(r'AIza[A-Za-z0-9_-]{25,}'),
        'OAuth client ID': re.compile(r'\d{8,}-[A-Za-z0-9_-]+\.apps\.googleusercontent\.com'),
        'Private key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
        'Drive file/folder ID': re.compile(r'drive\.google\.com/(?:file/d/|drive/folders/)[A-Za-z0-9_-]{12,}'),
        'NAS absolute path': re.compile(r'/(?:share|volume\d+)/[A-Za-z0-9_./-]+'),
        'Windows user path': re.compile(r'[A-Za-z]:[\\/]Users[\\/][A-Za-z0-9_.-]+'),
    }
    email_pattern = re.compile(r'[A-Za-z0-9_.+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})')
    for path in public_files():
        if not path.is_file():
            findings.append(f'{path.relative_to(ROOT)}: missing public file')
            continue
        source = path.read_text(encoding='utf-8')
        for number, line in enumerate(source.splitlines(), 1):
            for label, pattern in patterns.items():
                if pattern.search(line):
                    findings.append(f'{path.relative_to(ROOT)}:{number}: {label}')
            for match in email_pattern.finditer(line):
                if match.group(1) not in ('example.invalid', 'example.com', 'example.org', 'example.net'):
                    findings.append(f'{path.relative_to(ROOT)}:{number}: non-example email address')
        if path.suffix == '.py':
            tree = ast.parse(source)
            docs = {id(node.body[0].value) for node in ast.walk(tree)
                    if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body
                    and isinstance(node.body[0], ast.Expr)}
            if path.parent == ROOT / 'app':
                for node in ast.walk(tree):
                    if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                            and id(node) not in docs
                            and re.search(r'[\u3040-\u30ff\u3400-\u9fff]', node.value)):
                        findings.append(f'{path.relative_to(ROOT)}:{node.lineno}: untranslated literal')
                    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                            and node.func.id == 't' and node.args
                            and isinstance(node.args[0], ast.Constant)):
                        if node.args[0].value not in english_catalog():
                            findings.append(f'{path.relative_to(ROOT)}:{node.lineno}: missing message key')

    english = english_catalog()
    for path in (ROOT / 'app/locales').glob('*.json'):
        catalog = json.loads(path.read_text(encoding='utf-8'))
        if set(catalog) != set(english):
            findings.append(f'{path.name}: catalog keys differ')
        for key, message in catalog.items():
            if key not in english:
                continue
            if key.startswith('argparse.'):
                def fields(value):
                    return sorted(re.findall(r'%(?:\([^)]+\))?[srd]', value))
            else:
                def fields(value):
                    return sorted(name for _, name, _, _ in Formatter().parse(value) if name)
            if fields(message) != fields(english[key]):
                findings.append(f'{path.name}: placeholder mismatch at {key}')

    config = configparser.ConfigParser(interpolation=None)
    config.read(ROOT / 'config.example.ini', encoding='utf-8')
    assert all(not config.get(section, key) for section, key in (
        ('imap', 'host'), ('imap', 'user'), ('imap', 'password'),
        ('notification', 'topic'), ('notification', 'token'),
    ))
    assert not config.getboolean('imap', 'delete_after_import')
    assert not config.getboolean('notification', 'enabled')
    compose = yaml.safe_load((ROOT / 'docker-compose.example.yml').read_text(encoding='utf-8'))
    bridge = compose['services']['gmail-bridge']
    assert bridge['restart'] == 'unless-stopped'
    assert bridge['working_dir'] == '/app'
    assert 'command' not in bridge and 'entrypoint' not in bridge
    mounts = {mount['target']: mount for mount in bridge['volumes']}
    assert set(mounts) == {f'/app/{name}' for name in ('config.ini', 'credentials.json', 'token.json',
                                                       'data', 'backups', 'logs')}
    assert all(mount['type'] == 'bind' and mount['bind']['create_host_path'] is False
               for mount in mounts.values())
    assert mounts['/app/config.ini']['read_only']
    assert mounts['/app/credentials.json']['read_only']
    assert not mounts['/app/token.json'].get('read_only', False)
    assert not bridge.get('ports')
    image_compose = yaml.safe_load((ROOT / 'docker-compose.image.example.yml').read_text(encoding='utf-8'))
    image_bridge = image_compose['services']['gmail-bridge']
    assert 'build' not in image_bridge
    assert {k: v for k, v in bridge.items() if k not in ('build', 'image')} == {k: v for k, v in image_bridge.items() if k != 'image'}
    dockerfile = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
    assert 'CMD ["python", "-m", "app.service"]' in dockerfile
    assert 'install -y --no-install-recommends tzdata' in dockerfile
    assert [line for line in dockerfile.splitlines() if line.startswith('COPY ')] == [
        'COPY requirements.txt /app/requirements.txt', 'COPY app /app/app',
    ]
    return findings


def english_catalog():
    return json.loads((ROOT / 'app/locales/en.json').read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', action='store_true', help='Create dist/gmail-bridge-public.zip')
    args = parser.parse_args()
    findings = inspect()
    for finding in findings:
        print(finding)
    if findings:
        raise SystemExit(1)
    paths = public_files()
    print(f'PASS: {len(paths)} public files; heuristic secret scan, catalogs, Python AST, Compose structure.')
    print('Docker build and docker compose config require Docker; this script does not replace them.')
    if args.archive:
        destination = ROOT / 'dist/gmail-bridge-public.zip'
        destination.parent.mkdir(exist_ok=True)
        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for path in paths:
                archive.write(path, path.relative_to(ROOT).as_posix())
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        destination.with_suffix('.zip.sha256').write_text(
            f'{digest}  {destination.name}\n', encoding='ascii'
        )
        print(f'Archive: {destination.relative_to(ROOT)} ({len(paths)} files)')
        print(f'SHA256: {digest}')


if __name__ == '__main__':
    main()
