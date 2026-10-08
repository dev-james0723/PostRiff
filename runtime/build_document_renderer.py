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
SHA256 = '9833c61bfbec0905c6da54f82ef56123818661c9fec99706d9afece3ad7e9988'

def main():
    if os.uname().sysname != 'Linux' or not shutil.which('dnf'):
        raise SystemExit('Renderer bundling requires the cloud Amazon Linux build image.')
    root = Path(__file__).resolve().parents[1] / '.document-runtime'
    if (root / 'VERSION').exists() and (root / 'VERSION').read_text() == VERSION:
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
    shutil.copytree(office, root / 'office', dirs_exist_ok=True, symlinks=False)
    libdir = root / 'lib'
    libdir.mkdir(exist_ok=True)
    pending = [p for p in (office / 'program').iterdir() if p.is_file() and ('.so' in p.name or p.name == 'soffice.bin')]
    pending.append(Path('/usr/lib64/libseccomp.so.2'))
    seen = set()
    while pending:
        binary = pending.pop()
        if str(binary) in seen:
            continue
        seen.add(str(binary))
        if not binary.is_relative_to(office):
            shutil.copy2(binary, libdir / binary.name, follow_symlinks=True)
        output = subprocess.run(['ldd', str(binary)], capture_output=True, text=True, check=False).stdout
        for path in re.findall(r'=>\s+(/[^\s]+)', output):
            dep = Path(path)
            # Use the function runtime's glibc and loader, never a copied loader.
            if dep.name not in {'libc.so.6', 'libm.so.6', 'libdl.so.2', 'libpthread.so.0', 'librt.so.1', 'libresolv.so.2'}:
                pending.append(dep)
    shutil.copytree('/usr/share/fonts', root / 'fonts', dirs_exist_ok=True, symlinks=False)
    (root / 'VERSION').write_text(VERSION)
    print('Runtime bundle bytes', sum(p.stat().st_size for p in root.rglob('*') if p.is_file()))
    print('Bundled checksum-verified LibreOffice', VERSION)

if __name__ == '__main__':
    main()
