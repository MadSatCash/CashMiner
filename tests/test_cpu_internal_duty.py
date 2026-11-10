"""C-MT must honor the selected CPU percentage, including found batches."""
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mining_engine'))
import miner as engine


class InternalDutyTests(unittest.TestCase):
    def run_batches(self,percent,*,found=False):
        clock=[0.0];sleeps=[];calls=[];invalid=threading.Event()
        def sleep(seconds):sleeps.append(seconds);clock[0]+=seconds
        def scan(header,target,start,step,count,threads):
            clock[0]+=.1;calls.append(start)
            if len(calls)==2:invalid.set()
            return dict(found=found,hashes_done=count,last_nonce=start+count-1,
                        found_nonce=start,found_hash_le=bytes(32))
        solo=engine.BCHSoloMiner.__new__(engine.BCHSoloMiner)
        solo.invalidator=SimpleNamespace(invalidate_event=invalid,error_count=0)
        solo.c_scanner=SimpleNamespace(scan_mt=scan)
        solo.build_reward_coinbase=Mock(return_value=b'coinbase')
        solo.handle_found_block=Mock(return_value='found')
        with patch.multiple(engine,CPU_TARGET_PERCENT=percent,CPU_ENABLED=True,
                            CPU_THREADS_OVERRIDE=1,psutil=None,MAX_SECONDS_PER_TEMPLATE=0),\
             patch.object(engine,'time',SimpleNamespace(time=lambda:clock[0],sleep=sleep)),\
             patch.object(engine,'get_effective_template_refresh_seconds',return_value=0),\
             patch.object(engine,'log'),patch.object(engine,'log_block_estimate'):
            result=solo.mine_template_c_internal_threads(100,'00'*32,'1d00ffff',
                0x20000000,0,5000000000,[],[],None,'',0,0)
        return clock[0],sleeps,calls,result

    def test_25_and_50_percent_produce_different_wall_clock_work_rates(self):
        at25,s25,c25,_=self.run_batches(25)
        at50,s50,c50,_=self.run_batches(50)
        self.assertEqual(len(c25),2);self.assertEqual(len(c50),2)
        self.assertEqual(len(s25),2);self.assertEqual(len(s50),2)
        self.assertAlmostEqual(sum(s25),.6);self.assertAlmostEqual(sum(s50),.2)
        self.assertAlmostEqual(at25/at50,2)

    def test_found_batches_are_also_throttled(self):
        elapsed,sleeps,calls,result=self.run_batches(25,found=True)
        self.assertEqual(result,'found');self.assertEqual(len(calls),1)
        self.assertAlmostEqual(elapsed,.4);self.assertAlmostEqual(sum(sleeps),.3)


if __name__=='__main__':unittest.main()
