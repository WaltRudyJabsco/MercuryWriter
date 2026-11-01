#!/usr/bin/env python3
"""Install Mercury's standard-library runtime without changing writing data or AI setup."""
import argparse
import ast
import os
from pathlib import Path
import shlex
import shutil
import sys

RUNTIME = ('mercury','mercury_server.py','mercury_sync.py','mercury_fabric.py','mercury_session.py',
           'mercury_desk.py','mercury_desk.lua','README.md','README.txt','CHANGELOG.md','LICENSE')


def install(source, destination, bin_dir):
    pages = sorted(source.glob('Mercury_Writer*.html'))
    if not pages:
        raise ValueError('Mercury editor HTML is missing')
    files = [*RUNTIME, pages[-1].name]
    for name in files:
        path = source/name
        if not path.is_file(): raise ValueError('Missing Mercury runtime: '+name)
        if name.endswith('.py') or name == 'mercury': ast.parse(path.read_text())
    if source.resolve()==destination.resolve():raise ValueError('Install outside the source checkout')
    print("Install Mercury runtime: "+str(destination)+"; commands: "+str(bin_dir)+". Existing writing data and settings will be preserved.")
    destination.mkdir(parents=True,exist_ok=True)
    bin_dir.mkdir(parents=True,exist_ok=True)
    # Copy code only. Never replace config, library, state, history or manuscripts.
    for name in files:
        shutil.copy2(source/name,destination/name)
        if (destination/name).read_bytes()!=(source/name).read_bytes():
            raise OSError('Installed file verification failed: '+name)
    for old in destination.glob('Mercury_Writer*.html'):
        if old.name!=pages[-1].name:old.unlink()
    os.chmod(destination/'mercury',0o755)
    for name,command in [('mercury',[str(destination/'mercury')]),
                         ('mercury-server',[str(destination/'mercury_server.py')])]:
        launcher=bin_dir/name
        launcher.write_text('#!/bin/sh\nexec python3 '+shlex.join(command)+' "$@"\n')
        launcher.chmod(0o755)
    (destination/'Launch Mercury.command').write_text(
        '#!/bin/sh\nexec '+shlex.quote(str(bin_dir/'mercury'))+' open "$@"\n')
    (destination/'Launch Mercury.command').chmod(0o755)
    print('Mercury Writer runtime installed and verified: '+str(destination))
    print('Run mercury for Library → Mini, mercury open for the browser, or mercury --editor nvim')
    print('Local server starts when needed. AI, pairing and Fabric sync keep their existing settings.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-dir',type=Path,default=Path.home()/('Applications/Mercury-Writer' if sys.platform=='darwin' else '.local/share/mercury-writer'))
    parser.add_argument('--bin-dir',type=Path,default=Path.home()/'.local/bin')
    args=parser.parse_args()
    install(Path(__file__).resolve().parent,args.install_dir.expanduser().resolve(),args.bin_dir.expanduser().resolve())
