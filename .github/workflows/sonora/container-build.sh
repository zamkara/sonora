#!/usr/bin/env bash
set -euo pipefail
printf 'Server = https://geo.mirror.pkgbuild.com/$repo/os/$arch\n' > /etc/pacman.d/mirrorlist
# Python must be bootstrapped before querying the checked-in package dependency lists.
pacman -Syu --noconfirm --needed base-devel python git rustup cmake mold clang \
  vulkan-headers wayland-protocols desktop-file-utils alsa-lib dbus fontconfig \
  freetype2 hicolor-icon-theme libxcb libx11 libxcursor libxi libxkbcommon \
  libxkbcommon-x11 sqlite vulkan-icd-loader wayland curl sudo polkit ca-certificates
useradd --uid "$BUILDER_UID" --create-home builder
cp -a /inputs /build
mkdir -p /cargo /rustup /target
chown -R builder:builder /build /cargo /rustup /target
runuser -u builder -- env CARGO_HOME=/cargo RUSTUP_HOME=/rustup CARGO_TARGET_DIR=/target \
  CARGO_NET_GIT_FETCH_WITH_CLI=true SOURCE_DATE_EPOCH="$SOURCE_DATE_EPOCH" \
  python /repo/.github/workflows/sonora/build.py /build
pacman -U --noconfirm /build/release/sonora-*.pkg.tar.zst
sonora --arch-build-info
python -m py_compile /usr/lib/sonora/sonora-update /usr/lib/sonora/sonora-registry /usr/bin/sonora
ldd /usr/lib/sonora/sonora > /build/sonora.ldd
if grep -q 'not found' /build/sonora.ldd; then cat /build/sonora.ldd; exit 1; fi
desktop-file-validate /usr/share/applications/sonora.desktop
pacman -Qkk sonora
pacman-conf --repo sonora-managed Usage | grep -Fx Search
if pacman -Qqm | grep -Fx sonora; then echo 'Sonora leaked into foreign/AUR candidates' >&2; exit 1; fi
pacman -Sup --print-format '%n' > /build/system-updates.txt
if grep -Fx sonora /build/system-updates.txt; then echo 'Sonora leaked into system upgrades' >&2; exit 1; fi
# A second refresh must be idempotent and not duplicate includes.
/usr/lib/sonora/sonora-registry configure
test "$(grep -c '^Include = /etc/pacman.d/sonora-managed.conf$' /etc/pacman.conf)" = 1
pacman -R --noconfirm sonora
if grep -q 'Include = /etc/pacman.d/sonora-managed' /etc/pacman.conf; then echo 'Uninstall left repository references' >&2; exit 1; fi
test ! -e /var/lib/pacman/sync/sonora-managed.db
cp -a /build/release/. /output/
