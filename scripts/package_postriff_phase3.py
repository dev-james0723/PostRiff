#!/usr/bin/env python3
"""Explicit local-only packaging: allowlisted Python modules and shared web output."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
root=Path(__file__).resolve().parents[1]
def run(args,cwd=root):subprocess.run(args,cwd=cwd,check=True)
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--shell',action='store_true');args=parser.parse_args()
 run(['npm','--prefix','studio/web','run','build:hosted'])
 bundle=root/'desktop/bundle';bundle.mkdir(exist_ok=True)
 entry=root/'desktop/sidecar_entry.py';shutil.copy2(root/'scripts/postriff_phase3.py',entry)
 run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--name','postriff-sidecar','--distpath',str(bundle),'--workpath',str(root/'desktop/build-sidecar'),'--specpath',str(root/'desktop'),'--paths',str(root/'src'),'--add-data',str(root/'src/postriff_alpha/profile_builder_prompt.md')+':postriff_alpha','--hidden-import','PIL.Image','--hidden-import','PIL.JpegImagePlugin','--hidden-import','PIL.PngImagePlugin',str(entry)])
 target=bundle/'sidecar'
 if target.exists():shutil.rmtree(target)
 (bundle/'postriff-sidecar').rename(target)
 if (bundle/'web').exists():shutil.rmtree(bundle/'web')
 shutil.copytree(root/'studio/web/dist-alpha',bundle/'web')
 if args.shell:run(['npm','run','package:win' if sys.platform=='win32' else 'package:mac'],root/'desktop')
if __name__=='__main__':main()
