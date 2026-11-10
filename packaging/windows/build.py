"""Build the Windows ZIP in an explicit, disposable workspace.

No global Python packages, application data or original releases are modified.
Requires Python 3.10+, MSYS2 MinGW x64 GCC/windres and Internet for first build.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1]
VERSION = '2.17.1'
PYTHON_VERSION = '3.14.10'
PYTHON_URL = f'https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip'
PYTHON_SHA256 = '90905e64a840557d8c1bc4f5b74db3d7ee85e3ffb217611cac1c7813acea4159'
APPLICATION_PARTS = ('src', 'mining_engine', 'ui', 'assets', 'native')
IGNORE = shutil.ignore_patterns('__pycache__', '*.pyc', '.pytest_cache', '.git')

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def fetch(url, target, expected):
    if not target.exists():
        with urllib.request.urlopen(url, timeout=90) as response:
            target.write_bytes(response.read())
    if digest(target) != expected:
        raise RuntimeError(f'Checksum mismatch: {target.name}')

def run(command, **kwargs):
    subprocess.run(list(map(str, command)), check=True, **kwargs)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--gcc-bin', type=Path, default=Path('C:/msys64/mingw64/bin'))
    args = parser.parse_args()
    work, output = args.work.resolve(), args.output.resolve()
    if work == SOURCE or SOURCE in work.parents or work == output or work in output.parents:
        parser.error('Use a dedicated temporary directory outside the source/output')
    work.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    stage = work/'stage'/'CashMiner'
    if stage.exists():
        parser.error('Stage already exists. Use a fresh --work directory')
    app = stage/'_internal'/'app'
    runtime = stage/'_internal'/'python'
    app.mkdir(parents=True)
    runtime.mkdir(parents=True)
    downloads = work/'downloads'
    downloads.mkdir(exist_ok=True)
    archive = downloads/Path(PYTHON_URL).name
    fetch(PYTHON_URL, archive, PYTHON_SHA256)
    with zipfile.ZipFile(archive) as package:
        package.extractall(runtime)
    for name in APPLICATION_PARTS:
        shutil.copytree(SOURCE/name, app/name, ignore=IGNORE)
    shutil.copy2(SOURCE/'CashMiner.pyw', app/'CashMiner.pyw')
    (app/'scripts').mkdir()
    for name in ('hardware_probe.py', 'MIGRAR_DATOS.py'):
        shutil.copy2(SOURCE/'scripts'/name, app/'scripts'/name)
    site = runtime/'Lib'/'site-packages'
    site.mkdir(parents=True)
    # Embedded Python ignores PYTHONPATH and user site-packages. All children
    # use these same private module paths, including ranking and miner workers.
    (runtime/'python314._pth').write_text(
        'python314.zip\n.\nLib/site-packages\n../app/src\n../app/mining_engine\nimport site\n',
        encoding='ascii')
    (site/'sitecustomize.py').write_text(
        'import sys\nsys.dont_write_bytecode = True\n'
        '# Embedded isolation ignores PYTHONIOENCODING. The app reads child pipes as UTF-8.\n'
        'for stream in (sys.stdin, sys.stdout, sys.stderr):\n'
        '    if stream is not None and hasattr(stream, "reconfigure"):\n'
        '        stream.reconfigure(encoding="utf-8")\n', encoding='ascii')
    locks = HERE/'wheels.lock.json'
    wheel_dir = downloads/'wheels'
    wheel_dir.mkdir()
    if not locks.is_file():
        # First build only: subsequent builds fetch exclusively pinned hashes.
        run([sys.executable, '-m', 'pip', '--disable-pip-version-check', 'download',
             '--no-cache-dir', '--only-binary=:all:', '--platform', 'win_amd64',
             '--python-version', '3.14', '--implementation', 'cp', '--abi', 'cp314',
             '--dest', wheel_dir, 'cryptography==50.0.2', 'psutil==7.2.2'])
        pins = []
        for wheel in sorted(wheel_dir.glob('*.whl')):
            name, version = wheel.name.split('-')[:2]
            with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/{version}/json', timeout=40) as response:
                metadata = json.load(response)
            record = next(item for item in metadata['urls'] if item['filename'] == wheel.name)
            if digest(wheel) != record['digests']['sha256']:
                raise RuntimeError('Wheel hash differs from PyPI metadata')
            pins.append(dict(name=name, version=version, filename=wheel.name,
                             url=record['url'], sha256=digest(wheel)))
        locks.write_text(json.dumps(pins, indent=2)+'\n', encoding='utf-8')
    pins = json.loads(locks.read_text('utf-8'))
    for pin in pins:
        wheel = wheel_dir/pin['filename']
        fetch(pin['url'], wheel, pin['sha256'])
        with zipfile.ZipFile(wheel) as package:
            if any('.data/' in item for item in package.namelist()):
                raise RuntimeError('Wheel needs explicit .data installation support')
            package.extractall(site)
    build_env = os.environ.copy()
    build_env['PATH'] = str(args.gcc_bin)+os.pathsep+build_env.get('PATH', '')
    resource = work/'launcher.res.o'
    run([args.gcc_bin/'windres.exe', 'launcher.rc', '-O', 'coff', '-o', resource],
        cwd=HERE, env=build_env)
    run([args.gcc_bin/'gcc.exe', '-O2', '-Wall', '-Wextra', '-Wno-unused-parameter',
         '-municode', '-mwindows', '-static-libgcc', '-Wl,--no-insert-timestamp',
         HERE/'launcher.c', resource, '-o', stage/'CashMiner.exe'], env=build_env)
    notices = stage/'Licenses'
    notices.mkdir()
    shutil.copy2(SOURCE/'LICENSE', stage/'LICENSE')
    shutil.copy2(runtime/'LICENSE.txt', notices/'Python-LICENSE.txt')
    shutil.copy2(app/'ui'/'vendor'/'LICENSE-qrcodejs.txt', notices/'QRCodejs-LICENSE.txt')
    shutil.copy2(SOURCE/'src/cashminer/wallet/bip39_LICENSE.txt', notices/'BIP39-LICENSE.txt')
    for metadata in sorted(site.glob('*.dist-info')):
        destination = notices/metadata.name
        for file in metadata.rglob('*'):
            if file.is_file() and ('license' in file.name.lower() or 'notice' in file.name.lower()
                                   or 'licenses' in file.parts):
                target = destination/file.relative_to(metadata)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, target)
    compiler_licenses = args.gcc_bin.parent/'share'/'licenses'
    for name in ('crt', 'gcc-libs'):
        license_folder = compiler_licenses/name
        if not license_folder.is_dir():
            raise RuntimeError('Missing MinGW/GCC license directory: '+str(license_folder))
        shutil.copytree(license_folder, notices/('MinGW-'+name))
    (stage/'LEEME.txt').write_text((HERE/'LEEME.txt').read_text('utf-8'), encoding='utf-8')
    (stage/'THIRD_PARTY_NOTICES.txt').write_text(
        'CashMiner 2.17.1 Windows x64\n\n'
        'Python '+PYTHON_VERSION+': Python Software Foundation; see Licenses/Python-LICENSE.txt.\n'
        +'\n'.join(f"{p['name']} {p['version']}: see Licenses/{p['name']}-{p['version']}.dist-info/" for p in pins)
        +'\n\nQRCode.js: davidshimjs/contributors and Kazuhiko Arase; MIT.\n'
        'BIP39 word list: BIP-0039 authors; MIT. See Licenses/.\n'
        'OpenSSL and other bundled notices are included with the Python/cryptography license files.\n'
        'Native hashing DLLs/sources are from the author\'s cashminer_app project.\n'
        'CUDA/OpenCL/Windows vendor components retain their respective terms. Drivers are not bundled.\n'
        'Project code: MIT, Copyright (c) 2026 CashRider; see LICENSE.\n'
        'Native redistribution provenance must be finalized before public binary publication.\n',
        encoding='utf-8')
    manifest = dict(application=VERSION, python=PYTHON_VERSION, python_url=PYTHON_URL,
                    python_sha256=PYTHON_SHA256, wheels=pins,
                    compiler=subprocess.check_output([str(args.gcc_bin/'gcc.exe'), '--version'],
                                                     env=build_env, text=True).splitlines()[0],
                    files={p.relative_to(stage).as_posix(): digest(p)
                           for p in sorted(stage.rglob('*')) if p.is_file()})
    (stage/'BUILD_MANIFEST.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    target = output/'CashMiner-Windows.zip'
    if target.exists():
        raise RuntimeError('Output ZIP already exists; refusing to overwrite')
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for path in sorted(stage.rglob('*')):
            if path.is_file(): package.write(path, path.relative_to(stage.parent))
    print(json.dumps(dict(zip=str(target), sha256=digest(target), bytes=target.stat().st_size,
                          staged=str(stage)), indent=2))

if __name__ == '__main__':
    main()
