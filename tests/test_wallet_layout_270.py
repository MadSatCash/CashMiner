"""v2.7: visual-only unified wallet panel regression."""
from pathlib import Path
import re
import unittest
from html.parser import HTMLParser

ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'ui/index.html').read_text('utf-8')
class Structure(HTMLParser):
    def __init__(self):super().__init__();self.depth=0;self.dashboard_count=0;self.descendants=[];self.inside=False
    def handle_starttag(self, tag, attrs):
        d=dict(attrs);c=d.get('class','')
        if tag=='section' and 'wallet-dashboard' in c.split():
            self.dashboard_count+=1;self.inside=True;self.depth=1
        elif self.inside:self.depth+=1
        if self.inside and d.get('id') in {'walletNetworkSelect','walletGear','walletList','walletTitle','walletMeta','balance','balanceHelp','walletReceiveQr','walletReceiveAddress','walletAggregateAmount','sendPrepare','balanceHint'}:
            self.descendants.append(d['id'])
        if self.inside and tag=='section' and 'pane' in c.split() and 'wallet-dashboard' not in c.split():
            raise AssertionError('Separate wallet pane within unified dashboard')
    def handle_startendtag(self,tag,attrs):self.handle_starttag(tag,attrs);self.handle_endtag(tag)
    def handle_endtag(self,tag):
        if self.inside:
            self.depth-=1
            if self.depth==0:self.inside=False

class WalletLayout270(unittest.TestCase):
    def test_one_outer_wallet_panel_with_all_controls(self):
        x=Structure();x.feed(HTML)
        self.assertEqual(x.dashboard_count,1)
        for token in ['walletNetworkSelect','walletGear','walletList','walletTitle','walletMeta','balance','balanceHelp','walletReceiveQr','walletReceiveAddress','walletAggregateAmount','sendPrepare','balanceHint']:
            self.assertEqual(x.descendants.count(token),1,token)
    def test_same_height_and_responsive_stacking(self):
        self.assertIn('.layout{grid-template-columns:minmax(320px,390px) minmax(0,1fr);align-items:stretch',HTML)
        self.assertIn('.wallet-dashboard{min-height:612px',HTML)
        self.assertIn('.miners-pane{min-height:612px',HTML)
        self.assertIn('@media(max-width:680px)',HTML)
        self.assertNotIn('miner-tile-hint">',HTML)
    def test_no_logic_changes_in_wallet_actions(self):
        self.assertIn("api('/api/wallet/select'",HTML)
        self.assertIn("api('/api/wallet/network'",HTML)
        self.assertIn("api('/api/miner/start'",HTML)
        self.assertIn("api('/api/miner/stop'",HTML)
if __name__=='__main__':unittest.main()
