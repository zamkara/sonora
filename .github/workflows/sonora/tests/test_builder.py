import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

HELPERS=Path(__file__).resolve().parents[1];ROOT=HELPERS.parents[2]
sys.path.insert(0,str(HELPERS))
import common,prepare,build,publish,updater,registry


def plan():return {'repository':'zamkara/sonora','builder':'a'*40,'epoch':1234567890,
    'upstream':'sonorahq/sonora','upstream_commit':'b'*40,'upstream_tag':'v0.44.2',
    'version':'0.44.2','digest':'c'*64,'tag':'sha-'+'c'*64,'upstream_changelog':'Original upstream notes'}


class PlanningTests(unittest.TestCase):
    def test_identity_changes_with_either_source(self):
        self.assertEqual(common.identity('a'*40,'b'*40),common.identity('a'*40,'b'*40))
        self.assertNotEqual(common.identity('a'*40,'b'*40),common.identity('c'*40,'b'*40))
        self.assertNotEqual(common.identity('a'*40,'b'*40),common.identity('a'*40,'c'*40))
        with self.assertRaises(ValueError):common.identity('main','b'*40)

    def test_repository_validation(self):
        for value in ('../evil','owner/$(pwd)','owner/a/b'):
            with self.assertRaises(ValueError):common.repository(value)

    def test_unchanged_complete_release_skips_before_checkout(self):
        names=['catalog.json','SHA256SUMS','install.sh','PKGBUILD','SRCINFO','UPSTREAM_CHANGELOG.md',
               'sonora-source.tar.zst','native-updater.patch','upstream.json','sonora-0.44.2-1-x86_64.pkg.tar.zst']
        upstream={'tag_name':'v0.44.2','html_url':'https://github.com/sonorahq/sonora/releases/tag/v0.44.2','body':'exact original notes'}
        existing={'assets':[{'name':n} for n in names]}
        with tempfile.TemporaryDirectory() as d,patch.object(prepare,'gh_json',side_effect=[upstream,{'sha':'b'*40},existing]),patch('sys.stdout',new=io.StringIO()):
            path=Path(d)/'plan.json';self.assertFalse(prepare.plan(path,'zamkara/sonora','a'*40,'123'))
            self.assertEqual(json.loads(path.read_text())['upstream_changelog'],'exact original notes')

    def test_drafts_and_incomplete_releases_never_skip(self):
        self.assertFalse(prepare.complete({'draft':True,'assets':[]}))
        self.assertFalse(prepare.complete({'assets':[{'name':'catalog.json'}]}))

    def test_recipe_uses_pinned_git_and_keeps_package_name(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'plan.json').write_text(json.dumps(plan()))
            _,work=build.generate(root);text=(work/'PKGBUILD').read_text()
            self.assertIn('pkgname=sonora\n',text)
            self.assertIn('#commit='+'b'*40,text)
            self.assertIn('build --release --locked --package sonora',text)
            self.assertIn("'!lto'",text)
            self.assertIn('-C link-arg=-fuse-ld=mold',text)
            self.assertIn('conflicts=(\'sonora-bin\' \'sonora-git\')',text)
            self.assertIn('SONORA_ARCH_UPDATE_HELPER=/usr/lib/sonora/sonora-update',text)
            subprocess.run(['bash','-n',str(work/'PKGBUILD')],check=True)


class UpdaterTests(unittest.TestCase):
    def test_tampered_and_unlisted_downloads_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'file';p.write_bytes(b'correct')
            updater.verify(p,{'file':hashlib.sha256(b'correct').hexdigest()})
            with self.assertRaises(ValueError):updater.verify(p,{'file':'0'*64})
            with self.assertRaises(ValueError):updater.verify(p,{})

    def test_manifest_rejects_traversal_and_duplicates(self):
        for text in ('0'*64+'  ../bad','0'*64+'  file\n'+'0'*64+'  file'):
            with self.assertRaises(ValueError):updater.checksums(text)

    def test_up_to_date_check_offers_nothing(self):
        with patch.object(updater,'latest',return_value=('url',{}, {'package_version':'0.44.2-1'})),patch.object(updater,'installed_version',return_value='0.44.2-1'),patch.object(updater,'newer',return_value=False):
            self.assertIsNone(updater.check())

    def test_gui_and_cli_use_same_package_download(self):
        data={'package':'sonora-0.44.2-1-x86_64.pkg.tar.zst','version':'0.44.2','package_version':'0.44.2-1'}
        body=b'package';sums={data['package']:hashlib.sha256(body).hexdigest()}
        for gui in (True,False):
            def fetch(url,path):path.write_bytes(body)
            with patch.object(updater,'latest',return_value=('https://example/',sums,data)),patch.object(updater,'newer',return_value=True),patch.object(updater,'installed_version',return_value='0.44.1-1'),patch.object(updater,'identity',return_value=(1000,'123')),patch.object(os,'geteuid',return_value=1000),patch.object(os,'getuid',return_value=1000),patch.object(updater,'fetch',side_effect=fetch),patch.object(updater,'schedule_restart') as restart,patch.object(updater.subprocess,'run') as command,patch('builtins.open',unittest.mock.mock_open()),patch('sys.stdout',new=io.StringIO()):
                command.return_value=subprocess.CompletedProcess([],0,'sonora 0.44.2-1','')
                updater.install(gui=gui,parent=42 if gui else None)
                argv=command.call_args.args[0]
                self.assertEqual(argv[0],'/usr/bin/pkexec' if gui else '/usr/bin/sudo')
                self.assertIn('/usr/bin/pacman',argv)
                if gui:restart.assert_called_once_with(42)
                else:restart.assert_not_called()

    def test_checksum_failure_never_reaches_privileged_install(self):
        data={'package':'sonora-0.44.2-1-x86_64.pkg.tar.zst','version':'0.44.2','package_version':'0.44.2-1'}
        with patch.object(updater,'latest',return_value=('url',{data['package']:'0'*64},data)),patch.object(updater,'newer',return_value=True),patch.object(updater,'installed_version',return_value=None),patch.object(os,'geteuid',return_value=1000),patch.object(updater,'fetch',side_effect=lambda url,path:path.write_bytes(b'bad')),patch.object(updater.subprocess,'run') as command,patch('sys.stdout',new=io.StringIO()):
            with self.assertRaises(ValueError):updater.install()
            command.assert_not_called()

    def test_updater_never_runs_as_root(self):
        with patch.object(os,'geteuid',return_value=0),patch.object(updater,'latest') as latest:
            with self.assertRaises(RuntimeError):updater.install()
            latest.assert_not_called()

    def test_relaunch_rejects_different_user(self):
        with patch.object(updater,'identity',return_value=(2000,'123')),patch.object(os,'getuid',return_value=1000),patch.object(updater.subprocess,'Popen') as command:
            with self.assertRaises(ValueError):updater.schedule_restart(42)
            command.assert_not_called()

    def test_wrapper_routes_U_without_starting_gui(self):
        for arguments,target in ((['-U'],'/usr/lib/sonora/sonora-update'),(['spotify:track:123'],'/usr/lib/sonora/sonora')):
            with patch.object(sys,'argv',['sonora',*arguments]),patch.object(os,'execv',side_effect=SystemExit) as execute:
                with self.assertRaises(SystemExit):runpy.run_path(str(HELPERS/'sonora'),run_name='__main__')
                self.assertEqual(execute.call_args.args[0],target)


class RegistryTests(unittest.TestCase):
    def test_only_managed_sonora_is_known_to_system_helpers(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);local=root/'local';local.mkdir()
            p=local/'sonora-0.44.2-1';p.mkdir();desc=p/'desc'
            text='%NAME%\nsonora\n\n%VERSION%\n0.44.2-1\n\n%URL%\nhttps://github.com/zamkara/sonora\n\n'
            desc.write_text(text);output=root/'sync/sonora-managed.db'
            self.assertEqual(registry.refresh(local,output),1)
            with tarfile.open(output) as archive:self.assertEqual(archive.getnames(),['sonora-0.44.2-1/desc'])
            desc.write_text(text.replace('zamkara','sonorahq'))
            self.assertEqual(registry.refresh(local,output),0)

    def test_configuration_preserves_artcraft_and_other_options(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);path=root/'pacman.conf'
            original='[options]\nIgnorePkg = artcraft\n[extra]\nServer = https://example.test\n[artcraft-managed]\nUsage = Search\n'
            path.write_text(original)
            registry.configure(path,root/'backup',lambda:0)
            registry.configure(path,root/'backup',lambda:0)
            text=path.read_text()
            self.assertEqual(text.count(registry.OPTIONS),1)
            self.assertEqual(text.count(registry.REPOSITORY),1)
            self.assertIn('IgnorePkg = artcraft',text)
            self.assertIn('[artcraft-managed]\nUsage = Search',text)
            self.assertLess(text.index(registry.OPTIONS),text.index('[extra]'))

    def test_repo_has_no_upgrade_permission_and_options_cover_aur_names(self):
        self.assertIn('Usage = Search\n',(HELPERS/'sonora-managed.conf').read_text())
        self.assertIn('IgnorePkg = sonora sonora-bin sonora-git',(HELPERS/'sonora-managed.options').read_text())


class PublicationTests(unittest.TestCase):
    def test_superseded_builder_never_mutates_a_release(self):
        catalog={'repository':'zamkara/sonora','builder':'a'*40,'tag':'sha-'+'b'*64}
        with patch.object(publish,'validate',return_value=catalog),patch.object(publish,'current_builder',return_value='c'*40),patch.object(publish,'gh_json') as api,patch.object(publish.subprocess,'run') as command,patch('sys.stdout',new=io.StringIO()):
            publish.publish(Path('/unused'),'zamkara/sonora','a'*40)
            api.assert_not_called();command.assert_not_called()

    def test_current_builder_uses_actual_default_branch(self):
        with patch.object(publish,'gh_json',side_effect=[{'default_branch':'main'},{'sha':'a'*40}]) as api:
            self.assertEqual(publish.current_builder('zamkara/sonora'),'a'*40)
            self.assertEqual(api.call_args.args,('api','repos/zamkara/sonora/commits/main'))


class LayoutTests(unittest.TestCase):
    def test_clean_root_and_no_vendored_source(self):
        self.assertEqual({p.name for p in ROOT.iterdir() if p.name!='.git'},{'README.md','LICENSE','.github'})
        patchfile=HELPERS/'patches/0001-native-arch-updater.patch'
        self.assertLess(patchfile.stat().st_size,20000)
        self.assertFalse((ROOT/'Cargo.toml').exists())
        self.assertFalse((ROOT/'crates').exists())

    def test_source_patch_uses_one_shared_updater(self):
        text=(HELPERS/'patches/0001-native-arch-updater.patch').read_text()
        self.assertIn('SONORA_ARCH_UPDATE_HELPER',text)
        self.assertIn('["check", "--json"]',text)
        self.assertIn('"--parent-pid"',text)
        self.assertNotIn('api.spotify.com',text)


if __name__=='__main__':unittest.main()
