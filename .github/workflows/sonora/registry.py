#!/usr/bin/python3
"""Keep Sonora under its own updater using a search-only installed-version registry."""
import argparse
import datetime
import fcntl
import io
import os
from pathlib import Path
import shutil
import tarfile
import tempfile

DB=Path('/var/lib/pacman/sync/sonora-managed.db')
OPTIONS='Include = /etc/pacman.d/sonora-managed.options'
REPOSITORY='Include = /etc/pacman.d/sonora-managed.conf'


def metadata(text):
    result={}
    for block in text.strip().split('\n\n'):
        lines=block.splitlines()
        if lines and lines[0].startswith('%') and lines[0].endswith('%'):result[lines[0][1:-1]]=lines[1:]
    return result


def refresh(local=Path('/var/lib/pacman/local'),output=None):
    output=Path(output or DB)
    if not Path(local).is_dir():raise ValueError('Installed package database missing')
    entries=[]
    for source in sorted(Path(local).glob('sonora-*/desc')):
        info=metadata(source.read_text())
        if info.get('NAME')!=['sonora']:continue
        # Only this builder's own package opts in; an unrelated AUR package is not hidden.
        if info.get('URL')!=['https://github.com/zamkara/sonora']:continue
        version=info['VERSION'][0]
        if '/' in version or '\n' in version or version in ('.','..'):raise ValueError('Invalid version')
        keep=('NAME','BASE','VERSION','DESC','URL','ARCH','BUILDDATE','PACKAGER','LICENSE','REPLACES','GROUPS','DEPENDS','OPTDEPENDS','CONFLICTS','PROVIDES')
        text=''.join('%'+k+'%\n'+'\n'.join(info[k])+'\n\n' for k in keep if info.get(k))
        entries.append((f'sonora-{version}/desc',text.encode()))
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        fd,tmp=tempfile.mkstemp(prefix='.sonora-registry-',dir=output.parent)
        try:
            with os.fdopen(fd,'wb') as stream:
                with tarfile.open(fileobj=stream,mode='w:gz') as archive:
                    for name,body in entries:
                        item=tarfile.TarInfo(name);item.size=len(body);item.mode=0o644
                        archive.addfile(item,io.BytesIO(body))
                stream.flush();os.fsync(stream.fileno());os.fchmod(stream.fileno(),0o644)
            os.replace(tmp,output)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
    return len(entries)


def configure(config=Path('/etc/pacman.conf'),backup_dir=Path('/var/lib/sonora/backups'),refresher=refresh):
    old=config.read_text()
    text=old
    if OPTIONS not in text:
        # Option includes must be in [options], before the first repository section.
        lines=text.splitlines();found=False
        for i,line in enumerate(lines):
            if line.strip()=='[options]':lines.insert(i+1,OPTIONS);found=True;break
        if not found:raise ValueError('pacman.conf has no options section')
        text='\n'.join(lines)+'\n'
    if REPOSITORY not in text:text=text.rstrip()+'\n\n'+REPOSITORY+'\n'
    if text!=old:
        backup=backup_dir;backup.mkdir(parents=True,exist_ok=True,mode=0o700)
        shutil.copy2(config,backup/('pacman.conf.'+datetime.datetime.now().strftime('%Y%m%dT%H%M%S%f')))
        tmp=config.with_name('pacman.conf.sonora-tmp');tmp.write_text(text)
        shutil.copymode(config,tmp);os.replace(tmp,config)
    refresher()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['configure','refresh'])
    args=p.parse_args()
    if os.geteuid()!=0:raise SystemExit('Administrator privileges required')
    if args.command=='configure':configure()
    else:refresh()
