"""Selector observacional del log actual. Node es opcional para las pruebas offline."""
import re
import shutil
import subprocess
import unittest
from pathlib import Path

UI=Path(__file__).resolve().parents[1]/'ui'/'index.html'

@unittest.skipUnless(shutil.which('node'),'Node no instalado; la selección se prueba manualmente')
class UiSelectionTests(unittest.TestCase):
    def test_choose_log_new_session_manual_and_missing(self):
        source=UI.read_text('utf8')
        match=re.search(r'(function chooseMinerLog\(logs, state, selected, manual\)\{.*?\n\})',source,re.S)
        self.assertIsNotNone(match)
        script=match.group(1)+'''
const logs=[{name:'old.log'},{name:'new.log'}];
const check=(value,expected)=>{if(value!==expected)throw Error(JSON.stringify({value,expected}))};
check(chooseMinerLog(logs,{mining:true,active_log_name:null},'old.log',false),null);
check(chooseMinerLog(logs,{mining:true,active_log_name:'new.log'},'old.log',false),'new.log');
check(chooseMinerLog(logs,{mining:true,active_log_name:'new.log'},'old.log',true),'old.log');
check(chooseMinerLog(logs,{mining:false,active_log_name:null},'old.log',false),'old.log');
check(chooseMinerLog(logs,{mining:false,active_log_name:'new.log'},'old.log',false),'new.log');
'''
        r=subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=5)
        self.assertEqual(r.returncode,0,r.stderr)

if __name__=='__main__':unittest.main()
