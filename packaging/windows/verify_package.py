"""Integration checks using only the Python runtime in the extracted ZIP.

Run: <package>/_internal/python/python.exe verify_package.py --package <package>
     --work <temporary directory> --source <Codigo_fuente> [--gui]
Only local test services, throwaway data and public test addresses are used.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request

def wait_for(predicate, seconds=25):
    deadline = time.monotonic()+seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result: return result
        time.sleep(.1)
    raise TimeoutError('Package integration condition did not complete')

def verify_files(package):
    manifest = json.loads((package/'BUILD_MANIFEST.json').read_text('utf-8'))
    for name, expected in manifest['files'].items():
        assert hashlib.sha256((package/name).read_bytes()).hexdigest() == expected, name
    expected_names = set(manifest['files']) | {'BUILD_MANIFEST.json'}
    actual = {p.relative_to(package).as_posix() for p in package.rglob('*') if p.is_file()}
    assert actual == expected_names, actual ^ expected_names
    return len(expected_names)

def mining_checks(work, source):
    from cashminer.mining.hardware import inventory
    from cashminer.mining.bridge import MinerController, MiningSettings
    from cashminer.wallet.legacy_hd import address_from_secret
    # Reuse the existing independent Stratum wire/share validator.
    sys.path.insert(0, str(source/'tests'))
    from test_stratum_216 import Pool
    hardware = inventory(True)
    cases = [('CPU', None)] + [(gpu['backend'].upper(), gpu['slot'])
                              for gpu in hardware['gpus'] if gpu['supported']]
    results = []
    for label, slot in cases:
        pool = Pool()
        lines, exits = [], []
        controller = MinerController(lines.append, lambda *args: exits.append(args))
        try:
            overrides = {gpu['slot']: (25 if gpu['slot'] == slot else 0)
                         for gpu in hardware['gpus']}
            settings = MiningSettings(network='testnet3', mode='pool',
                reward_address=address_from_secret(1, 'testnet3'),
                cpu_percent=25 if slot is None else 0, gpu_percent=0,
                gpu_overrides=overrides, pool_url=f'stratum+tcp://127.0.0.1:{pool.port}',
                pool_user='package-test', pool_password='local-test')
            controller.start(settings)
            private_child = Path(controller.proc.args[0]).resolve()
            assert private_child == Path(sys.executable).resolve(), private_child
            wait_for(lambda: pool.shares or exits, seconds=50)
            assert pool.shares, '\n'.join(lines[-30:])
            assert not pool.errors, pool.errors
            if slot is not None:
                assert any(label.lower() in line.lower() for line in lines), label
            results.append(dict(backend=label, shares_independently_validated=len(pool.shares),
                                private_python=True, pid=controller.proc.pid))
        finally:
            controller.stop(timeout=7)
            pool.close()
            (work/(label+'-miner.log')).write_text('\n'.join(lines), encoding='utf-8')
        assert not controller.running()
    return results

def ranking_check(work):
    from cashminer.network.peer_store import PeerStore
    from cashminer.network.peer_rankings import PeerRankingProcess
    root = work/'ranking-data'
    store = PeerStore(root/'networks'/'testnet3.sqlite')
    store.add_peer('127.0.0.1', 18333, source_type='manual', source_value='package-test')
    worker = PeerRankingProcess(root, interval=300)
    worker.start()
    try:
        worker.request('testnet3')
        wait_for(lambda: worker.process and worker.process.poll() is None)
        process = worker.process
        assert Path(process.args[0]).resolve() == Path(sys.executable).resolve()
        # The persisted ranking publication is the observable completion signal.
        wait_for(lambda: list((root/'rankings').glob('*')), seconds=15)
    finally:
        worker.close()
    assert process.poll() is not None
    return dict(private_python=True, exited=True)

def gui_check(package, work):
    import psutil
    env = os.environ.copy()
    env['CASHMINER_DATA_DIR'] = str(work/'gui-data')
    env['CASHMINER2_DATA_DIR'] = env['CASHMINER_DATA_DIR']
    launcher = subprocess.Popen([str(package/'CashMiner.exe')], cwd=work, env=env,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    url, token = None, None
    try:
        def get_url():
            if launcher.poll() is not None: raise RuntimeError('Launcher exited before opening UI')
            for child in psutil.Process(launcher.pid).children(recursive=True):
                if child.name().lower() != 'pythonw.exe': continue
                for connection in child.net_connections(kind='tcp'):
                    if connection.status == psutil.CONN_LISTEN and connection.laddr.ip == '127.0.0.1':
                        return f'http://127.0.0.1:{connection.laddr.port}'
        url = wait_for(get_url, seconds=35)
        html = urllib.request.urlopen(url+'/', timeout=10).read().decode('utf-8')
        token = re.search(r"const TOKEN='([^']+)'", html).group(1)
        for asset in ('/assets/qrcode.min.js','/assets/i18n.js','/assets/fiat.js','/assets/Logo.png','/favicon.ico'):
            assert urllib.request.urlopen(url+asset, timeout=10).status == 200
        def api(path):
            request = urllib.request.Request(url+path, headers={'X-CashMiner-Session':token})
            return json.load(urllib.request.urlopen(request, timeout=25))
        state = api('/api/state')
        hardware = api('/api/hardware')
        assert hardware['gpus'] and hardware['cpus']
        (work/'gui-ready.json').write_text(json.dumps(dict(url=url,launcher_pid=launcher.pid)), encoding='utf-8')
        # A bounded pause allows optional visual inspection of the actual window.
        gate = work/'gui-inspected'
        wait_for(lambda: gate.exists(), seconds=180)
        return dict(launcher=True, html=True, assets=5, state=True,
                    gpu_count=len(hardware['gpus']))
    finally:
        if url and token:
            request = urllib.request.Request(url+'/api/exit', data=b'{}',
                headers={'Content-Type':'application/json','X-CashMiner-Session':token}, method='POST')
            try: urllib.request.urlopen(request, timeout=10).close()
            except OSError: pass
        try: launcher.wait(timeout=20)
        except subprocess.TimeoutExpired:
            for child in reversed(psutil.Process(launcher.pid).children(recursive=True)):
                try: child.terminate()
                except psutil.NoSuchProcess: pass
            launcher.terminate(); launcher.wait(timeout=10)
        assert launcher.returncode == 0, launcher.returncode
        log_files = list((work/'gui-data').rglob('cashminer_app_*.log'))
        assert log_files
        logs = '\n'.join(p.read_text('utf-8') for p in log_files)
        assert 'Cierre normal de CashMiner' in logs, logs[-2000:]
        assert 'Excepción no controlada' not in logs and 'Fallo en el proceso principal' not in logs

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--gui', action='store_true')
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    os.environ['CASHMINER_DATA_DIR'] = str(args.work/'mining-data')
    os.environ['CASHMINER2_DATA_DIR'] = os.environ['CASHMINER_DATA_DIR']
    assert Path(sys.executable).resolve() == (args.package/'_internal/python/python.exe').resolve()
    import cashminer
    assert (args.package/'_internal/app/src') in Path(cashminer.__file__).resolve().parents
    report = dict(files_verified=verify_files(args.package),
                  python=sys.version, interpreter=sys.executable,
                  stdout_encoding=sys.stdout.encoding)
    report['mining'] = mining_checks(args.work, args.source)
    report['ranking'] = ranking_check(args.work)
    if args.gui: report['gui'] = gui_check(args.package, args.work)
    report['files_verified_after'] = verify_files(args.package)
    (args.work/'package_result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))

if __name__ == '__main__': main()
