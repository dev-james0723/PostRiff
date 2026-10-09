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
BUNDLE_REVISION = VERSION + '-headless-minimal-3'
DYNAMIC_PROVIDERS = ('libseccomp.so.2','libsoftokn3.so','libfreebl3.so','libfreeblpriv3.so','libnssckbi.so')
SHA256 = '9833c61bfbec0905c6da54f82ef56123818661c9fec99706d9afece3ad7e9988'

# Keep the exact Writer / Calc / Impress / Draw conversion stack. Core needs
# ooofonts and images to satisfy its RPM dependencies; package only the fonts
# and theme actually required by the private, headless document renderer.
INSTALL_RPMS = frozenset({
    'libobasis26.2-core', 'libobasis26.2-ooofonts', 'libobasis26.2-images',
    'libobasis26.2-en-US', 'libobasis26.2-writer', 'libobasis26.2-calc',
    'libobasis26.2-impress', 'libobasis26.2-draw', 'libobasis26.2-math',
    'libobasis26.2-graphicfilter', 'libobasis26.2-xsltfilter',
    'libobasis26.2-ooolinguistic',
    'libreoffice26.2', 'libreoffice26.2-ure', 'libreoffice26.2-en-US',
    'libreoffice26.2-writer', 'libreoffice26.2-calc',
    'libreoffice26.2-impress', 'libreoffice26.2-draw',
    'libreoffice26.2-math',
})
# Offline headless conversion does not use GUI artwork, templates, help,
# database tooling, macro wizards or Apple/Works import filters. Do not remove
# share/config/soffice.cfg or libclucene/libpdfiumlo: they are required even
# in headless mode. Verified against DOCX/XLSX/PPTX, legacy DOC/XLS/PPT,
# ODT/ODS/ODP, RTF, HTML, TXT and CSV round trips.
OMIT_OFFICE_DIRS = (
    'help', 'share/gallery', 'share/template', 'share/wizards',
    'share/basic', 'share/tipoftheday', 'share/Scripts',
    'share/xpdfimport', 'share/firebird', 'share/xdg',
)
OMIT_OFFICE_LIBS = (
    'libldapbe2lo.so', 'libmysqlclo.so', 'libmwaw-0.3-lo.so.3',
    'libetonyek-0.1-lo.so.1', 'libdbalo.so',
    'libstaroffice-0.0-lo.so.0', 'libvbaobjlo.so', 'libvbaswobjlo.so',
    'libClp.so.1', 'libCoinUtils.so.3', 'libCgl.so.1',
    'libCbc.so.3', 'libCbcSolver.so.3', 'libwps-0.4-lo.so.4',
    'libcuilo.so', 'libswuilo.so', 'libscuilo.so', 'libsduilo.so',
    'libslideshowlo.so', 'xpdfimport',
)
# FONTCONFIG_FILE in library_preview.py points at the bundled root/fonts;
# curate there rather than copying the same full font families twice.
FONT_PREFIXES = ('Carlito', 'Liberation', 'NotoSans', 'NotoSerif',
                 'DejaVuSans', 'DejaVuSerif')

def main():
    if os.uname().sysname != 'Linux' or not shutil.which('dnf'):
        raise SystemExit('Renderer bundling requires the cloud Amazon Linux build image.')
    root = Path(__file__).resolve().parents[1] / '.document-runtime'
    archive = root.parent / '.document-runtime.tar.xz'
    manifest = root.parent / '.document-runtime.tar.xz.sha256'
    # Retain only the compressed artifact in the deployed function; the
    # expanded native runtime is too large for the standard Python Lambda.
    if archive.exists() and manifest.exists() and not root.exists():
        return
    if root.exists():
        shutil.rmtree(root)
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
        available = sorted((work / 'rpms').rglob('*.rpm'))
        rpms = []
        selected = set()
        for rpm in available:
            for package in INSTALL_RPMS:
                if rpm.name.startswith(package + '-' + VERSION + '.'):
                    rpms.append(str(rpm))
                    selected.add(package)
                    break
        missing = INSTALL_RPMS - selected
        if missing:
            raise SystemExit('LibreOffice release missing required RPMs: ' + ', '.join(sorted(missing)))
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

    bundled = root / 'office'
    shutil.copytree(office, bundled, dirs_exist_ok=True, symlinks=False)
    # Minimal, deterministic fonts still support realistic document rasterization.
    font_target = root / 'fonts'
    font_target.mkdir(exist_ok=True)
    font_source = bundled / 'share/fonts/truetype'
    if font_source.exists():
        for font in font_source.glob('*.ttf'):
            if font.name.startswith(FONT_PREFIXES):
                shutil.copy2(font, font_target / font.name)
        shutil.rmtree(font_source.parent)
    # Amazon Linux DejaVu fallback covers symbols/mono when absent in Office.
    for font in Path('/usr/share/fonts').rglob('*.ttf'):
        if font.name.startswith(('DejaVuSans', 'DejaVuSerif')) and not (font_target / font.name).exists():
            shutil.copy2(font, font_target / font.name)
    for relative in OMIT_OFFICE_DIRS:
        candidate = bundled / relative
        if candidate.is_dir():
            shutil.rmtree(candidate)
        elif candidate.exists():
            candidate.unlink()
    for theme in (bundled / 'share/config').glob('images_*'):
        if theme.name != 'images_colibre.zip':
            theme.unlink()
    for library in OMIT_OFFICE_LIBS:
        candidate = bundled / 'program' / library
        if candidate.is_file():
            candidate.unlink()
    # Interactive dialog layouts are not required to decode documents. Keep
    # cross-module UI and the Impress tab view used by actual headless imports.
    # Trace: 13 real DOCX/XLSX/PPTX/legacy/HTML/text/CSV format conversions,
    # followed by test_library_preview (real pages, colour, seccomp, pagination).
    ui_root = bundled / 'share/config/soffice.cfg'
    for ui in ui_root.rglob('*.ui'):
        relative = ui.relative_to(ui_root).as_posix()
        if not (relative.startswith(('svt/ui/', 'cui/ui/'))
                or relative == 'modules/simpress/ui/tabviewbar.ui'):
            ui.unlink()
    # Trace only retained ELF files. Otherwise optional deleted modules pull
    # irrelevant shared libraries back into the function bundle.
    link_env['LD_LIBRARY_PATH'] = str(bundled / 'program')
    libdir = root / 'lib'
    libdir.mkdir(exist_ok=True)
    # Office opens plugins and helper executables after startup. Inspect every
    # ELF rather than guessing from filename suffixes (oosplash has no .so).
    pending = []
    for binary in (bundled / 'program').rglob('*'):
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
        if not binary.is_relative_to(bundled):
            shutil.copy2(binary, libdir / binary.name, follow_symlinks=True)
        output = subprocess.run(['ldd', str(binary)], capture_output=True, text=True, env=link_env, check=False).stdout
        for path in re.findall(r'=>\s+(/[^\s]+)', output):
            dep = Path(path)
            # Use the function runtime's glibc and loader, never a copied loader.
            if dep.name not in {'libc.so.6', 'libm.so.6', 'libdl.so.2', 'libpthread.so.0', 'librt.so.1', 'libresolv.so.2'}:
                pending.append(dep)
    (root / 'VERSION').write_text(BUNDLE_REVISION)
    bundle_bytes = sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
    print('Renderer expanded bytes', bundle_bytes)
    if bundle_bytes > 385_000_000:
        raise SystemExit('Expanded renderer exceeds verified 385MB /tmp budget')
    # The function bundle must not contain the expanded 375MB Office tree.
    # Python stdlib xz is available in both build and Lambda; the immutable
    # archive is verified by SHA-256 before use and extracted into /tmp lazily.
    compressed = archive.with_name(archive.name + '.new')
    try:
        with tarfile.open(compressed, mode='w:xz', preset=3) as tar:
            tar.add(root, arcname='.', recursive=True)
        archive_bytes = compressed.stat().st_size
        if archive_bytes > 160_000_000:
            raise SystemExit('Compressed renderer exceeds 160MB function budget')
        with compressed.open('rb') as opened:
            archive_sha = hashlib.file_digest(opened, 'sha256').hexdigest()
        os.replace(compressed, archive)
        manifest.write_text(archive_sha + '\\n')
        shutil.rmtree(root)
        print('Renderer compressed bytes', archive_bytes)
        print('Renderer manifest SHA-256', archive_sha)
        print('Bundled checksum-verified LibreOffice', VERSION)
    finally:
        if compressed.exists():
            compressed.unlink()

if __name__ == '__main__':
    main()
