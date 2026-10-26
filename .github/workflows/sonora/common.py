"""Validated GitHub and content identity helpers."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

UPSTREAM='sonorahq/sonora'
HELPERS=Path(__file__).resolve().parent


def sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda:f.read(1024*1024),b''):digest.update(data)
    return digest.hexdigest()


def repository(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*/[A-Za-z0-9][A-Za-z0-9_.-]*',value):raise ValueError('Invalid repository')
    return value


def gh_json(*args,input=None):
    p=subprocess.run(['gh',*args],input=input,capture_output=True,text=True)
    if p.returncode:
        if 'HTTP 404' in p.stderr:return None
        raise RuntimeError(p.stderr.strip() or 'GitHub request failed')
    return json.loads(p.stdout)


def identity(upstream,builder):
    if not all(re.fullmatch(r'[a-f0-9]{40}',s) for s in (upstream,builder)):raise ValueError('Full commit identities required')
    return hashlib.sha256((upstream+'\n'+builder+'\n').encode()).hexdigest()
