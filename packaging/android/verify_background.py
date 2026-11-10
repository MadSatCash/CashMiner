"""Opt-in emulator regression: mine in background and with the screen off.

Uses the existing independent Stratum verifier, no public network or user funds.
All temporary output belongs to --work. Requires an already running emulator
with the APK installed and MainActivity open; never runs against a real phone.
"""
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
    parser=argparse.ArgumentParser()
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--serial',default='emulator-5556')
    parser.add_argument('--adb-port',type=int,default=5038)
    parser.add_argument('--hold-seconds',type=int,default=20)
    args=parser.parse_args()
    if not re.fullmatch(r'emulator-\d+',args.serial):raise ValueError('Disposable emulator only')
    work=args.work.resolve();tools=json.loads((work/'tools.json').read_text('utf-8-sig'))
    adb_path=Path(tools['sdk'])/'platform-tools/adb.exe'
    def adb(*values):
        return subprocess.check_output([str(adb_path),'-P',str(args.adb_port),'-s',args.serial,*values],
                                       text=True,stderr=subprocess.STDOUT,timeout=25)
    logs=adb('logcat','-d','-s','CashMinerStartup:I','CashMinerSelfTest:I')
    urls=re.findall(r'UI (http://127\.0\.0\.1:(\d+)/)',logs)
    if not urls:raise RuntimeError('APK has not finished startup')
    origin,port=urls[-1];origin=origin.rstrip('/')
    adb('forward','tcp:'+port,'tcp:'+port)
    html=urllib.request.urlopen(origin,timeout=15).read().decode()
    token=re.search(r"const TOKEN='([^']+)'",html)[1]
    def api(route,data=None):
        request=urllib.request.Request(origin+route,
            data=None if data is None else json.dumps(data).encode(),
            headers={'X-CashMiner-Session':token,'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=15) as response:return json.load(response)
    def state():return api('/api/state?miner_network=testnet3')
    def mining_wake_lock_held():
        # dumpsys also contains a history of released locks; inspect live locks.
        text=adb('shell','dumpsys','power')
        live=text.split('Wake Locks:',1)[1].split('Suspend Blockers:',1)[0]
        return 'CashMiner:MiningCPU' in live
    def wait_for(test,seconds,message):
        until=time.monotonic()+seconds
        while not test():
            if time.monotonic()>=until:raise AssertionError(message)
            time.sleep(.2)
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tests'))
    from test_stratum_216 import Pool
    pool=Pool();pool.difficulty=Decimal('0.0001')
    original=adb('shell','settings','get','global','always_finish_activities').strip()
    report={}
    try:
        adb('reverse',f'tcp:{pool.port}',f'tcp:{pool.port}')
        api('/api/miner/connection',dict(network='testnet3',mode='pool',
            pool_url=f'stratum+tcp://127.0.0.1:{pool.port}',pool_user='android.local',pool_password='x'))
        api('/api/miner/start',dict(network='testnet3'))
        wait_for(lambda:len(pool.shares)>=1,45,'No independently valid native CPU share')
        pid=adb('shell','pidof','org.cashminer.android:miner_testnet3').strip()
        first=len(pool.shares)
        # Exercise Android's "Don't keep activities" developer setting as well.
        adb('shell','settings','put','global','always_finish_activities','1')
        adb('shell','input','keyevent','KEYCODE_HOME')
        time.sleep(args.hold_seconds)
        assert state()['mining'],'Mining stopped after leaving/destroying the Activity'
        assert len(pool.shares)>first,'No work while Activity was absent'
        report['background_mining_continued']=True
        middle=len(pool.shares)
        adb('shell','input','keyevent','KEYCODE_SLEEP')
        time.sleep(args.hold_seconds)
        assert state()['mining'],'Mining stopped with screen off'
        assert len(pool.shares)>middle,'No independently verified shares with screen off'
        assert adb('shell','pidof','org.cashminer.android:miner_testnet3').strip()==pid
        assert mining_wake_lock_held(),'Missing mining wake lock'
        report['screen_off_mining_continued']=True
        api('/api/miner/stop',dict(network='testnet3'))
        wait_for(lambda:not state()['mining'],12,'Stop did not finish in background')
        wait_for(lambda:not mining_wake_lock_held(),5,'Wake lock leaked after stop')
        report['stop_in_background_released_wake_lock']=True
        adb('shell','settings','put','global','always_finish_activities','0')
        adb('shell','input','keyevent','KEYCODE_WAKEUP')
        adb('shell','wm','dismiss-keyguard')
        adb('shell','am','start','-n','org.cashminer.android/.MainActivity')
        time.sleep(2)
        # The recreated Activity must attach to the same server and session history.
        newer=adb('logcat','-d','-s','CashMinerStartup:I')
        assert re.findall(r'UI (http://127\.0\.0\.1:\d+/)',newer)[-1]==origin+'/'
        assert not state()['mining']
        assert not pool.errors,pool.errors
        report.update(activity_reopened_same_app=True,accepted_shares=len(pool.shares),
                      held_seconds_per_phase=args.hold_seconds,pool_errors=pool.errors)
        (work/'background-result.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report),flush=True)
    except Exception:
        print(json.dumps({key:state().get(key) for key in ('mining','miner_state','last_error')}),flush=True)
        print(json.dumps(api('/api/logs?kind=miner&network=testnet3')['lines'][-8:]),flush=True)
        raise
    finally:
        try:api('/api/miner/stop',dict(network='testnet3'))
        except Exception:pass
        pool.close()
        adb('shell','settings','put','global','always_finish_activities',original)
        adb('shell','input','keyevent','KEYCODE_WAKEUP')


if __name__=='__main__':main()
