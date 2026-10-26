#!/usr/bin/env python3
"""Generate a pinned PKGBUILD, compile Sonora on Arch, and stage complete release inputs."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

from common import HELPERS,repository,sha256

RUNTIME=['glibc','gcc-libs','alsa-lib','dbus','fontconfig','freetype2','hicolor-icon-theme',
         'libxcb','libx11','libxcursor','libxi','libxkbcommon','libxkbcommon-x11','sqlite',
         'vulkan-icd-loader','wayland','python','curl','sudo','polkit','ca-certificates']
BUILD=['base-devel','git','rustup','cmake','mold','clang','vulkan-headers','wayland-protocols','desktop-file-utils']
FILES=['sonora','updater.py','registry.py','sonora.install','sonora-managed.conf','sonora-managed.options','95-sonora-registry.hook']


def quote(value):return "'"+str(value).replace("'","'\\''")+"'"


def generate(root):
    plan=json.loads((root/'plan.json').read_text());repo=repository(plan['repository'])
    work=root/'package';work.mkdir(parents=True,exist_ok=True)
    for name in FILES:shutil.copy2(HELPERS/name,work/name)
    updater=(work/'updater.py').read_text().replace("REPOSITORY='zamkara/sonora'",'REPOSITORY='+repr(repo))
    (work/'updater.py').write_text(updater)
    registry=(work/'registry.py').read_text().replace("'https://github.com/zamkara/sonora'",repr('https://github.com/'+repo))
    (work/'registry.py').write_text(registry)
    shutil.copy2(HELPERS/'patches/0001-native-arch-updater.patch',work/'native-updater.patch')
    shutil.copy2(HELPERS.parents[2]/'LICENSE',work/'LICENSE.Almatera')
    meta={k:plan[k] for k in ('repository','builder','upstream','upstream_commit','upstream_tag','version','tag','digest')}
    meta.update(architecture='x86_64',package_version=f"{plan['version']}-1.{plan['epoch']}")
    (work/'build.json').write_text(json.dumps(meta,indent=2)+'\n')
    sources=['sonora-source::git+https://github.com/sonorahq/sonora.git#commit='+plan['upstream_commit'],
             'native-updater.patch','LICENSE.Almatera','build.json',*FILES]
    sums=['SKIP']+[sha256(work/name) for name in sources[1:]]
    recipe=f'''# Generated from an immutable official Sonora release commit.
pkgname=sonora
pkgver={plan['version']}
pkgrel=1.{plan['epoch']}
pkgdesc='A native music streaming client, built with Rust and GPUI'
arch=('x86_64')
url='https://github.com/{repo}'
license=('GPL-3.0-or-later' 'LicenseRef-Almatera-Incubator')
depends=({' '.join(map(quote,RUNTIME))})
makedepends=({' '.join(map(quote,BUILD))})
optdepends=('vulkan-intel: Intel Vulkan driver' 'vulkan-radeon: AMD Vulkan driver'
            'nvidia-utils: NVIDIA Vulkan driver' 'pipewire-alsa: audio through PipeWire'
            'pulseaudio-alsa: audio through PulseAudio' 'webkit2gtk-4.1: browser-based sign-in')
conflicts=('sonora-bin' 'sonora-git')
install='sonora.install'
options=('!strip' '!debug')
source=({' '.join(map(quote,sources))})
sha256sums=({' '.join(map(quote,sums))})
prepare() {{
  cd "$srcdir/sonora-source"
  git apply --3way --index "$srcdir/native-updater.patch"
  python -c 'import tomllib; from pathlib import Path; assert tomllib.loads(Path("Cargo.toml").read_text())["workspace"]["package"]["version"] == "{plan['version']}", "Release tag and Cargo version differ"'
}}
build() {{
  cd "$srcdir/sonora-source"
  local toolchain
  toolchain=$(python -c 'import tomllib; from pathlib import Path; print(tomllib.loads(Path("rust-toolchain.toml").read_text())["toolchain"]["channel"])')
  [[ "$toolchain" =~ ^[0-9]+\\.[0-9]+\\.[0-9]+$ ]] || {{ echo 'Expected a pinned Rust toolchain' >&2; return 1; }}
  rustup toolchain install "$toolchain" --profile minimal --component rustfmt
  export SONORA_ARCH_UPDATE_HELPER=/usr/lib/sonora/sonora-update
  export CARGO_TARGET_DIR="${{CARGO_TARGET_DIR:-$PWD/target}}"
  export CARGO_BUILD_JOBS=2
  export CARGO_PROFILE_RELEASE_LTO=false
  export CARGO_PROFILE_RELEASE_CODEGEN_UNITS=8
  cargo +"$toolchain" fmt --package state --package sonora -- --check
  cargo +"$toolchain" build --release --locked --package sonora
}}
check() {{
  cd "$srcdir/sonora-source"
  "${{CARGO_TARGET_DIR:-$srcdir/sonora-source/target}}/release/sonora" --arch-build-info | grep -F 'updater=/usr/lib/sonora/sonora-update'
}}
package() {{
  local source="$srcdir/sonora-source"
  install -Dm755 "${{CARGO_TARGET_DIR:-$srcdir/sonora-source/target}}/release/sonora" "$pkgdir/usr/lib/sonora/sonora"
  install -Dm755 "$srcdir/sonora" "$pkgdir/usr/bin/sonora"
  install -Dm755 "$srcdir/updater.py" "$pkgdir/usr/lib/sonora/sonora-update"
  install -Dm755 "$srcdir/registry.py" "$pkgdir/usr/lib/sonora/sonora-registry"
  install -Dm644 "$srcdir/build.json" "$pkgdir/usr/share/sonora/build.json"
  install -Dm644 "$source/assets/linux/sonora.desktop" "$pkgdir/usr/share/applications/sonora.desktop"
  install -dm755 "$pkgdir/usr/share/icons"
  cp -a "$source/assets/linux/icons/." "$pkgdir/usr/share/icons/"
  install -Dm644 "$source/assets/linux/sonora.svg" "$pkgdir/usr/share/icons/hicolor/scalable/apps/sonora.svg"
  install -Dm644 "$source/COPYING" "$pkgdir/usr/share/licenses/sonora/COPYING"
  install -Dm644 "$source/THIRD-PARTY.md" "$pkgdir/usr/share/licenses/sonora/THIRD-PARTY.md"
  install -Dm644 "$srcdir/LICENSE.Almatera" "$pkgdir/usr/share/licenses/sonora/LICENSE.Almatera"
  install -Dm644 "$srcdir/sonora-managed.conf" "$pkgdir/etc/pacman.d/sonora-managed.conf"
  install -Dm644 "$srcdir/sonora-managed.options" "$pkgdir/etc/pacman.d/sonora-managed.options"
  install -Dm644 "$srcdir/95-sonora-registry.hook" "$pkgdir/usr/share/libalpm/hooks/95-sonora-registry.hook"
}}
'''
    (work/'PKGBUILD').write_text(recipe)
    return plan,work


def build(root):
    plan,work=generate(root)
    subprocess.run(['makepkg','--cleanbuild','--nodeps','--noconfirm'],cwd=work,check=True)
    packages=list(work.glob('sonora-*.pkg.tar.zst'))
    if len(packages)!=1:raise RuntimeError('Expected one native Sonora package')
    release=root/'release';release.mkdir(exist_ok=True)
    package=packages[0];shutil.copy2(package,release/package.name)
    meta=json.loads((work/'build.json').read_text());meta['schema']=1;meta['package']=package.name
    (release/'catalog.json').write_text(json.dumps(meta,indent=2)+'\n')
    (release/'UPSTREAM_CHANGELOG.md').write_text(plan['upstream_changelog'])
    (release/'upstream.json').write_text(json.dumps(plan,indent=2)+'\n')
    for name in ('PKGBUILD','native-updater.patch'):shutil.copy2(work/name,release/name)
    with (release/'SRCINFO').open('w') as f:subprocess.run(['makepkg','--printsrcinfo'],cwd=work,stdout=f,check=True)
    installer=(HELPERS/'install.sh.in').read_text().replace('@REPOSITORY@',plan['repository']).replace('@TAG@',plan['tag'])
    (release/'install.sh').write_text(installer)
    # Corresponding modified source and packaging helpers are release assets only,
    # never tracked in the policy repository. Exclude Git state and build products.
    source=work/'src/sonora-source';arch=source/'arch-packaging';arch.mkdir(exist_ok=True)
    for name in ('PKGBUILD','LICENSE.Almatera','build.json','native-updater.patch',*FILES):shutil.copy2(work/name,arch/name)
    shutil.copy2(release/'SRCINFO',arch/'SRCINFO')
    subprocess.run(['tar','--exclude=.git','--exclude=target','-I','zstd -T2','-cf',str(release/'sonora-source.tar.zst'),'-C',str(source),'.'],check=True)
    (release/'SHA256SUMS').write_text(''.join(f'{sha256(p)}  {p.name}\n' for p in sorted(release.iterdir()) if p.name!='SHA256SUMS'))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path)
    p.add_argument('--generate-only',action='store_true');args=p.parse_args()
    (generate if args.generate_only else build)(args.root.resolve())
