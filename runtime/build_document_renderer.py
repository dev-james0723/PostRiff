"""Build-only LibreOffice bundle for the existing Amazon Linux Vercel API.

Run in the cloud build image, never on the Mac. Official archive is checksum
locked; shared libraries are copied from the same AL2023 distribution as runtime.
"""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

VERSION = '26.2.6'
BUNDLE_REVISION = VERSION + '-elf-closure-2'
DYNAMIC_PROVIDERS = ('libseccomp.so.2','libsoftokn3.so','libfreebl3.so','libfreeblpriv3.so','libnssckbi.so')
SHA256 = '9833c61bfbec0905c6da54f82ef56123818661c9fec99706d9afece3ad7e9988'

def main():
    if os.uname().sysname != 'Linux' or not shutil.which('dnf'):
        raise SystemExit('Renderer bundling requires the cloud Amazon Linux build image.')
    root = Path(__file__).resolve().parents[1] / '.document-runtime'
    if (root / 'VERSION').exists() and (root / 'VERSION').read_text() == BUNDLE_REVISION:
        return
    root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rafii-renderer-build-') as work:
        work = Path(work)
        name = f'LibreOffice_{VERSION}_Linux_x86-64_rpm.tar.gz'
        archive = work / name
        urllib.request.urlretrieve(f'https://download.documentfoundation.org/libreoffice/stable/{VERSION}/rpm/x86_64/{name}', archive)
        if hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest() != SHA256:
            raise SystemExit('Official LibreOffice archive checksum mismatch.')
        with tarfile.open(archive) as tar:
            tar.extractall(work / 'rpms', filter='data')
        rpms = sorted(str(p) for p in (work / 'rpms').rglob('*.rpm'))
        subprocess.run(['dnf', '-y', '--setopt=install_weak_deps=False', 'install', 'libXinerama', 'cups-libs', 'dbus-glib', 'cairo', 'libseccomp', 'nss', 'fontconfig', 'dejavu-sans-fonts', 'dejavu-serif-fonts', *rpms], check=True)
    office = next(Path('/opt').glob('libreoffice26.2'))
    # RPM packages do not declare every dynamically loaded headless dependency.
    # Resolve the actual binary's complete transitive graph before packaging.
    link_env = {**os.environ, 'LD_LIBRARY_PATH': str(office / 'program')}
    for attempt in range(4):
        links = subprocess.run(['ldd', str(office / 'program/soffice.bin')], capture_output=True, text=True, env=link_env, check=False)
        missing = sorted(set(re.findall(r'(\S+) => not found', links.stdout)))
        if not missing:
            break
        if attempt == 3:
            raise SystemExit('Unresolved document runtime dependencies: ' + ', '.join(missing))
        subprocess.run(['dnf', '-y', '--setopt=install_weak_deps=False', 'install', *['/usr/lib64/' + name for name in missing]], check=True)
    absent_providers = ['/usr/lib64/' + name for name in DYNAMIC_PROVIDERS if not (Path('/usr/lib64') / name).is_file()]
    if absent_providers:
        subprocess.run(['dnf', '-y', '--setopt=install_weak_deps=False', 'install', *absent_providers], check=True)
    shutil.copytree(office, root / 'office', dirs_exist_ok=True, symlinks=False)
    libdir = root / 'lib'
    libdir.mkdir(exist_ok=True)
    # Office opens plugins and helper executables after startup. Inspect every
    # ELF rather than guessing from filename suffixes (oosplash has no .so).
    pending = []
    for binary in (office / 'program').rglob('*'):
        if binary.is_file():
            with binary.open('rb') as source:
                if source.read(4) == b'\x7fELF':
                    pending.append(binary)
    # NSS opens these crypto/token providers dynamically; ldd cannot discover
    # them from libnss3. Include their ordinary transitive dependencies too.
    for name in DYNAMIC_PROVIDERS:
        provider = Path('/usr/lib64') / name
        if not provider.is_file():
            raise SystemExit('Required runtime provider missing: ' + name)
        pending.append(provider)
    seen = set()
    while pending:
        binary = pending.pop()
        if str(binary) in seen:
            continue
        seen.add(str(binary))
        if not binary.is_relative_to(office):
            shutil.copy2(binary, libdir / binary.name, follow_symlinks=True)
        output = subprocess.run(['ldd', str(binary)], capture_output=True, text=True, env=link_env, check=False).stdout
        for path in re.findall(r'=>\s+(/[^\s]+)', output):
            dep = Path(path)
            # Use the function runtime's glibc and loader, never a copied loader.
            if dep.name not in {'libc.so.6', 'libm.so.6', 'libdl.so.2', 'libpthread.so.0', 'librt.so.1', 'libresolv.so.2'}:
                pending.append(dep)
    shutil.copytree('/usr/share/fonts', root / 'fonts', dirs_exist_ok=True, symlinks=False)
    (root / 'VERSION').write_text(BUNDLE_REVISION)
    print('Runtime bundle bytes', sum(p.stat().st_size for p in root.rglob('*') if p.is_file()))
    print('Bundled checksum-verified LibreOffice', VERSION)

if __name__ == '__main__':
    main()
