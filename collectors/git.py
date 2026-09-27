import hashlib
import subprocess

def _git(root, *args):
    try:
        result = subprocess.run(
            ['git', '-C', str(root), *args],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=2, check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None

def collect_git(root):
    branch = _git(root, 'branch', '--show-current')
    porcelain = _git(root, 'status', '--porcelain')
    commit = _git(root, 'rev-parse', '--short', 'HEAD')
    if branch is None or porcelain is None:
        return {'available': False}
    changes = len(porcelain.splitlines()) if porcelain else 0
    return {
        'available': True,
        'branch': branch or 'DETACHED',
        'commit': commit,
        '_fingerprint': hashlib.sha256(porcelain.encode('utf-8')).hexdigest(),
        'clean': changes == 0,
        'changes': changes,
    }
