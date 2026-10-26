#!/usr/bin/python3
"""One checksummed package updater shared by the Sonora UI and sonora -U."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

REPOSITORY='zamkara/sonora'
PACKAGE='sonora'
HELPER='/usr/lib/sonora/sonora-update'


def checksums(text):
    result={}
    for line in text.splitlines():
        match=re.fullmatch(r'([a-f0-9]{64})  ([A-Za-z0-9_.+\-]+)',line)
        if not match or match[2] in result:raise ValueError('Invalid checksum manifest')
        result[match[2]]=match[1]
    return result


def verify(path,sums):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda:f.read(1024*1024),b''):h.update(data)
    if sums.get(path.name)!=h.hexdigest():raise ValueError('Checksum mismatch: '+path.name)


def fetch(url,path):
    subprocess.run(['curl','-fLsS','--proto','=https','--proto-redir','=https',
                    '--retry','3','--connect-timeout','20','--max-time','300',
                    '-o',str(path),url],check=True,capture_output=True,text=True)


def latest():
    if platform.machine()!='x86_64':raise RuntimeError('This native package supports x86_64 only')
    request=urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/releases/latest',
                                   headers={'User-Agent':'sonora-updater','Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(request,timeout=30) as response:release=json.load(response)
    tag=release.get('tag_name','')
    if release.get('draft') or release.get('prerelease') or not re.fullmatch(r'sha-[a-f0-9]{64}',tag):raise ValueError('Invalid native release')
    base=f'https://github.com/{REPOSITORY}/releases/download/{tag}/'
    with tempfile.TemporaryDirectory(prefix='sonora-check-') as directory:
        root=Path(directory);fetch(base+'SHA256SUMS',root/'SHA256SUMS')
        sums=checksums((root/'SHA256SUMS').read_text())
        fetch(base+'catalog.json',root/'catalog.json');verify(root/'catalog.json',sums)
        data=json.loads((root/'catalog.json').read_text())
    if data['repository']!=REPOSITORY or data['tag']!=tag or data['architecture']!='x86_64':raise ValueError('Native release identity mismatch')
    filename=data['package']
    if not re.fullmatch(r'sonora-[0-9][A-Za-z0-9_.+\-]*-x86_64\.pkg\.tar\.zst',filename):raise ValueError('Invalid native package name')
    if filename not in sums:raise ValueError('Package checksum missing')
    return base,sums,data


def installed_version():
    result=subprocess.run(['/usr/bin/pacman','-Q',PACKAGE],capture_output=True,text=True)
    if result.returncode:return None
    parts=result.stdout.strip().split()
    if len(parts)!=2 or parts[0]!=PACKAGE:raise ValueError('Unexpected installed package metadata')
    return parts[1]


def newer(offered,current):
    if current is None:return True
    result=subprocess.run(['/usr/bin/vercmp',offered,current],capture_output=True,text=True,check=True)
    return int(result.stdout)>0


def check():
    base,sums,data=latest()
    if not newer(data['package_version'],installed_version()):return None
    return {'version':data['version'],'page':f'https://github.com/{REPOSITORY}/releases/tag/{data["tag"]}',
            'installer':base+data['package'],'sums':base+'SHA256SUMS'}


def identity(pid):
    path=Path('/proc')/str(pid)
    try:
        fields=(path/'stat').read_text().rsplit(')',1)[1].split()
        return path.stat().st_uid,fields[19]
    except (OSError,IndexError):return None


def schedule_restart(parent):
    token=identity(parent)
    if token is None:return
    if token[0]!=os.getuid():raise ValueError('Refusing to supervise a different user process')
    subprocess.Popen([HELPER,'relaunch','--wait-pid',str(parent),'--start-ticks',token[1]],
                     stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)


def relaunch(pid,ticks):
    token=(os.getuid(),ticks)
    deadline=time.monotonic()+120
    while identity(pid)==token:
        if time.monotonic()>=deadline:return
        time.sleep(0.2)
    subprocess.Popen(['/usr/bin/sonora'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL,start_new_session=True)


def install(gui=False,parent=None):
    if os.geteuid()==0:raise RuntimeError('Run as your regular user; only the package transaction requests administrator privileges')
    if gui and (not parent or identity(parent) is None or identity(parent)[0]!=os.getuid()):raise ValueError('Invalid GUI parent process')
    base,sums,data=latest()
    if not newer(data['package_version'],installed_version()):
        print('Sonora is already current.')
        if gui:schedule_restart(parent)
        return
    print('Downloading Sonora '+data['version']+'...')
    with tempfile.TemporaryDirectory(prefix='sonora-install-') as directory:
        package=Path(directory)/data['package'];fetch(base+package.name,package);verify(package,sums)
        metadata=subprocess.run(['/usr/bin/pacman','-Qp',str(package)],capture_output=True,text=True,check=True).stdout.strip().split()
        if metadata!=[PACKAGE,data['package_version']]:raise ValueError('Downloaded package metadata mismatch')
        if gui:
            subprocess.run(['/usr/bin/pkexec','/usr/bin/pacman','-U','--noconfirm','--',str(package)],
                           stdin=subprocess.DEVNULL,capture_output=True,text=True,check=True)
        else:
            with open('/dev/tty','rb',buffering=0) as tty:
                subprocess.run(['/usr/bin/sudo','--','/usr/bin/pacman','-U','--',str(package)],stdin=tty,check=True)
    if gui:schedule_restart(parent)
    else:print('Sonora updated. Restart the application to use the new build.')


def main():
    p=argparse.ArgumentParser(description=__doc__);commands=p.add_subparsers(dest='command',required=True)
    c=commands.add_parser('check');c.add_argument('--json',action='store_true')
    i=commands.add_parser('install');i.add_argument('--gui',action='store_true');i.add_argument('--parent-pid',type=int)
    r=commands.add_parser('relaunch');r.add_argument('--wait-pid',type=int,required=True);r.add_argument('--start-ticks',required=True)
    args=p.parse_args()
    if args.command=='check':print(json.dumps(check()))
    elif args.command=='install':install(args.gui,args.parent_pid)
    else:relaunch(args.wait_pid,args.start_ticks)


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,RuntimeError,subprocess.CalledProcessError) as error:
        print('sonora updater:',error,file=sys.stderr);sys.exit(1)
