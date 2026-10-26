#!/usr/bin/env python3
"""Pin the latest stable upstream tag and skip an unchanged complete native release."""
import argparse
import json
import os
from pathlib import Path
import re

from common import UPSTREAM,gh_json,identity,repository


def complete(release):
    if not release or release.get('draft') or release.get('prerelease'):return False
    names={a['name'] for a in release.get('assets',[])}
    return {'catalog.json','SHA256SUMS','install.sh','PKGBUILD','SRCINFO','UPSTREAM_CHANGELOG.md',
            'sonora-source.tar.zst','native-updater.patch'}<=names and any(
                n.startswith('sonora-') and n.endswith('-x86_64.pkg.tar.zst') for n in names)


def plan(output,repo,builder,epoch):
    repo=repository(repo)
    release=gh_json('api',f'repos/{UPSTREAM}/releases/latest')
    if not release or release.get('draft') or release.get('prerelease'):raise RuntimeError('No stable upstream release')
    tag=release['tag_name']
    if not re.fullmatch(r'v?\d+\.\d+\.\d+',tag):raise ValueError('Unsupported stable version tag')
    commit=gh_json('api',f'repos/{UPSTREAM}/commits/{tag}')
    if not commit:raise RuntimeError('Upstream tag cannot be resolved')
    revision=commit['sha'];digest=identity(revision,builder);native_tag='sha-'+digest
    published=gh_json('api',f'repos/{repo}/releases/tags/{native_tag}')
    needed=not complete(published)
    data={'schema':1,'repository':repo,'builder':builder,'epoch':int(epoch),
          'upstream':UPSTREAM,'upstream_commit':revision,'upstream_tag':tag,
          'version':tag.removeprefix('v'),'digest':digest,'tag':native_tag,
          'upstream_release_url':release['html_url'],'upstream_changelog':release.get('body') or ''}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(data,indent=2)+'\n')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write(f'build={str(needed).lower()}\nupstream={revision}\n')
    print('Native build required: '+tag if needed else 'Identical complete release exists; skipped before source checkout or compilation')
    return needed


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--repository',required=True);p.add_argument('--builder',required=True);p.add_argument('--epoch',required=True)
    a=p.parse_args();plan(a.output,a.repository,a.builder,a.epoch)
