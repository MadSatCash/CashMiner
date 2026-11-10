"""Opt-in emulator check: independent per-network sessions and Stop actions."""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request


def main():
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True)
    p.add_argument('--serial',default='emulator-5556');args=p.parse_args()
    if not re.fullmatch(r'emulator-\d+',args.serial):raise ValueError('Disposable emulator only')
    work=args.work.resolve();tools=json.loads((work/'tools.json').read_text('utf-8-sig'))
    def adb(*values):return subprocess.check_output([str(Path(tools['sdk'])/'platform-tools/adb.exe'),
        '-P','5038','-s',args.serial,*values],text=True,stderr=subprocess.STDOUT,timeout=25)
    logs=adb('logcat','-d','-s','CashMinerStartup:I')
    origin,port=re.findall(r'UI (http://127\.0\.0\.1:(\d+)/)',logs)[-1]
    origin=origin.rstrip('/');adb('forward','tcp:'+port,'tcp:'+port)
    html=urllib.request.urlopen(origin).read().decode();token=re.search(r"const TOKEN='([^']+)'",html)[1]
    def api(route,data=None):
        request=urllib.request.Request(origin+route,data=None if data is None else json.dumps(data).encode(),
            headers={'X-CashMiner-Session':token,'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=20) as response:return json.load(response)
    def wait(test,message):
        end=time.monotonic()+35
        while not test():
            if time.monotonic()>end:raise AssertionError(message)
            time.sleep(.2)
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tests'))
    from test_stratum_216 import Pool
    networks=('testnet3','testnet4');pools={};original=api('/api/state')
    settings={n:api('/api/state?miner_network='+n)['settings'] for n in networks}
    report={}
    try:
        for mode in ('automatic','continuous'):api('/api/peers/global',dict(mode=mode,enabled=False))
        for network in networks:
            pool=Pool();pool.difficulty=Decimal('.0001');pools[network]=pool
            adb('reverse',f'tcp:{pool.port}',f'tcp:{pool.port}')
            api('/api/settings',dict(network=network,cpu_percent=25,gpu_percent=0,hardware_controls_v2=True))
            api('/api/miner/connection',dict(network=network,mode='pool',pool_url=f'stratum+tcp://127.0.0.1:{pool.port}',pool_user='parallel.local',pool_password='x'))
            api('/api/miner/start',dict(network=network))
        wait(lambda:all(pool.shares for pool in pools.values()),'Both sessions must produce independently valid shares')
        assert api('/api/state')['active_mining_count']==2
        keys=adb('shell','cmd','notification','list')
        for identifier in (22,23):assert f'|org.cashminer.android|{identifier}|' in keys,keys
        before={n:len(pool.shares) for n,pool in pools.items()}
        adb('shell','input','keyevent','KEYCODE_HOME');time.sleep(15)
        state=api('/api/state')
        assert all(state['mining_sessions'][n]['mining'] for n in networks)
        assert all(len(pools[n].shares)>before[n] for n in networks)
        api('/api/miner/stop',dict(network='testnet3'))
        wait(lambda:not api('/api/state')['mining_sessions']['testnet3']['mining'],'First session did not stop')
        assert api('/api/state')['mining_sessions']['testnet4']['mining']
        before_second=len(pools['testnet4'].shares);time.sleep(3)
        assert len(pools['testnet4'].shares)>before_second
        keys=adb('shell','cmd','notification','list')
        assert '|org.cashminer.android|22|' not in keys
        assert '|org.cashminer.android|23|' in keys
        api('/api/miner/stop',dict(network='testnet4'))
        wait(lambda:api('/api/state')['active_mining_count']==0,'Second session did not stop')
        assert not any(pool.errors for pool in pools.values())
        report=dict(parallel_networks=list(networks),independent_notifications=True,
                    parallel_background=True,stop_one_keeps_other_mining=True,
                    accepted_shares={n:len(pool.shares) for n,pool in pools.items()})
        (work/'parallel-result.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
    finally:
        for network in networks:
            try:api('/api/miner/stop',dict(network=network))
            except Exception:pass
        for pool in pools.values():pool.close()
        for mode,key in (('automatic','explorer_auto_master'),('continuous','explorer_continuous_master')):
            api('/api/peers/global',dict(mode=mode,enabled=original[key]))
        for network,values in settings.items():
            api('/api/settings',dict(network=network,cpu_percent=values['cpu_percent'],
                gpu_percent=values['gpu_percent'],hardware_controls_v2=True))
        adb('shell','am','start','-n','org.cashminer.android/.MainActivity')


if __name__=='__main__':main()
