# Sonora

Sonora built from the latest stable [upstream release](https://github.com/sonorahq/sonora)
inside Arch Linux, distributed as a managed Arch package. The application and
command remain **Sonora** and `sonora`.

## Install

After the first successful release:

```sh
curl -fsSL https://github.com/zamkara/sonora/releases/latest/download/install.sh | bash
```

The installer verifies the release catalog and package checksums before asking
pacman to install anything. Run as your normal user. It needs Python, curl, sudo,
an interactive terminal and x86_64 Arch Linux / Omarchy. If needed, install Python
and curl through your normal system package manager first.

An existing `sonora-bin` or `sonora-git` conflicts with this package; pacman asks
before replacing it. Sonora's user settings, library, cache, account sessions and
playlists use the upstream locations and are not deleted or migrated.

## Update

```sh
sonora -U
```

The application's existing update notification uses the same package updater as
`sonora -U`. It checks this repository's published catalog, downloads the Arch
package, verifies SHA-256 and package identity, and asks for administrator
authentication only for the pacman transaction. CLI confirmation reads `/dev/tty`,
including when the installer is piped into Bash.

An update started inside the app waits for installation to succeed, then quits
and starts the updated Sonora. Restart supervision is limited to the original
user process and stops waiting after two minutes. A CLI update leaves a running
Sonora alone and asks you to restart it. Cancellation or an installation failure
uses the app's existing update-error state; an unverified package is not installed.
The existing **Check for updates** preference continues to control background
checks inside the app. There is no additional daemon or system update timer.

## Independent package management

The package installs a root-owned local catalog, `sonora-managed`, with
`Usage = Search`. It records only the installed version and is not a source for
system upgrades. This prevents yay and paru from classifying the managed Sonora
as an AUR candidate. Separate `IgnorePkg` protection covers `sonora`, `sonora-bin`
and `sonora-git` in pacman's options. Omarchy's pacman/yay-based updater uses the
same configuration. No terminal-output filtering, fake installed-package removal,
or wrappers around yay/paru/pacman are used.

A transaction hook refreshes the catalog after package changes. Include directives
are idempotent, other package exclusions and repositories (including Artcraft) are
preserved, and the previous pacman configuration is backed up under
`/var/lib/sonora/backups`. Normal installed-package queries still show Sonora;
only update ownership is separated. An administrator can deliberately override
these controls, but ordinary system/AUR upgrades cannot replace this build.

## Automated builds

The workflow checks the latest stable upstream release every hour at minute 17,
plus manual dispatch and pushes to `main`. The schedule uses GitHub's UTC cron;
the hourly interval is independent of local timezone. Schedules are best-effort,
can be delayed, run only on the default branch, and may be disabled for public
repositories after 60 days of inactivity.

The planner resolves the release tag to a full immutable commit and hashes it
with the full builder commit. An identical complete published release is skipped
before source checkout or compilation. Drafts, incomplete releases and request
failures never count as a successful unchanged release.

The build:

1. Downloads the pinned upstream source only in an ignored temporary build tree.
2. Applies the small updater-integration patch, failing on an upstream conflict.
3. Uses upstream's exact Rust toolchain and `cargo build --release --locked` on Arch.
4. Installs the package in the disposable container, checks libraries, desktop entry,
   updater integration, package integrity and the system-updater blocker, then removes it.
5. Publishes the package, source, checksums, original upstream changelog and installer
   only after those checks pass.

Only Linux x86_64 is currently supported. Compilation uses two jobs and eight codegen
units without cross-crate LTO to keep the GPUI build within hosted-runner memory.
Rust dependencies and targets are cached. The first build can take significantly
longer than later builds; a build has a two-hour limit.

Every published release is non-prerelease and includes a one-line installer.
Drafts are temporary upload staging only; publication uses numeric release IDs
and verifies every uploaded asset before publishing. Upstream release notes are
preserved verbatim in `UPSTREAM_CHANGELOG.md`; long notes link that asset instead
of inventing a changelog.

SHA-256 verifies integrity over HTTPS; it is not an independent publisher signature.
The trust boundary includes this repository and its GitHub release permissions.

## Remove

```sh
sudo pacman -R sonora
```

Package removal removes this project's repository references and catalog as well
as its package files. It leaves all Sonora user data untouched. Dependencies are
not removed automatically by that command.

## Source and repository layout

Only `README.md`, `LICENSE` and `.github/` are tracked at the root. Implementation,
patches and tests are in `.github/workflows/sonora`. No upstream repository, Rust
workspace, vendored dependency tree or built binary is committed. Build products
stay in ignored `.github/workflows/.build/` directories.

A release includes the corresponding modified Sonora source as
`sonora-source.tar.zst`, its locked dependency references, the updater patch,
`PKGBUILD`, `SRCINFO`, package catalog and original upstream provenance. Packaging
helpers are included in the source asset under `arch-packaging/`. Rust crates and
git dependencies are fetched at their locked revisions during reproduction.
To reproduce with the PKGBUILD, keep its listed helper files together and provide
`CARGO_HOME`, `RUSTUP_HOME` and `CARGO_TARGET_DIR` or let their defaults apply.

Builder code is covered by the [Almatera Incubator License](LICENSE). Sonora and
the derived Rust integration patch retain upstream's GPL-3.0-or-later license.
The package carries the upstream GPL, third-party notices and the helper license;
the root builder license does not relicense Sonora.

```sh
python3 -m unittest discover -s .github/workflows/sonora/tests -v
```
