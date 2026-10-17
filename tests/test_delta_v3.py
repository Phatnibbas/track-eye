import ast
import contextlib
import io
from pathlib import Path
import shutil
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from delta_bridge.v3 import V3Reference, V3Snapshot, parse_cfg
from tools.delta_v3_validate import load_config, run

ROOT=Path(__file__).resolve().parent.parent
CFG='min=2 max=30 homedir=0 maxhz=4000 accel=1500 homefast=800 homeslow=150 led=1 enc=1 encdir=-1'


def snapshot(offline=False):
    return ['STAT fault=False eyes=1+2 verg=0.00']+[
        f'STAT n{n} {"OFF" if offline and n==2 else "ON"} IDLE err=NONE homed=1 sw=0 pos=1.993 target=0.000'
        for n in range(1,7)]


def make_reference(path):
    for name in ('main.py','spm_ik.py','proto3.py'):
        shutil.copy2(ROOT/'firmware'/name,path/name)
    # Deliberate test fixture, never a deployment neutral/default.
    (path/'neutral3.txt').write_text('1 15 15 15\n2 15 15 15\n')
    ref=V3Reference(path,(1,2),0)
    for n in range(1,7):
        ref.apply_cfg(f'CFG n{n} '+CFG)
    return ref


class V3ContractTests(unittest.TestCase):
    def test_header_and_all_six_nodes_needed_for_ready(self):
        s=V3Snapshot((1,2),0,1)
        for line in snapshot()[:-1]:
            s.consume(line,1)
        self.assertFalse(s.ready(1,.5))
        s.consume(snapshot()[-1],1.1)
        self.assertTrue(s.ready(1.2,.5))
        self.assertFalse(s.ready(2,.5))

    def test_wrong_eyes_vergence_legacy_header_and_duplicate_block(self):
        for header in ('STAT fault=False eyes=1 verg=0.00','STAT fault=False eyes=1+2 verg=1.00',
                       'STAT fault=False queue=0 inflight=-'):
            with self.assertRaises(ValueError):
                V3Snapshot((1,2),0,1).consume(header,1)
        s=V3Snapshot((1,2),0,1)
        s.consume(snapshot()[0],1)
        s.consume(snapshot()[1],1)
        with self.assertRaises(ValueError):
            s.consume(snapshot()[1],1)
        self.assertFalse(s.ready(1,1))

    def test_offline_fault_reboot_invalidate(self):
        for event in ('FAULT test','ERR n2 OFFLINE','EVT n2 BOOT fw=3 reset=HARD_RESET'):
            s=V3Snapshot((1,2),0,1)
            for line in snapshot():
                s.consume(line,1)
            s.consume(event,1.1)
            self.assertFalse(s.ready(1.1,1))
        s=V3Snapshot((1,2),0,1)
        for line in snapshot(offline=True):
            s.consume(line,1)
        self.assertFalse(s.ready(1,1))

    def test_cfg_rejects_missing_duplicate_nonfinite(self):
        for line in ('CFG n1 min=2 max=30','CFG n1 '+CFG+' min=2','CFG n1 '+CFG.replace('max=30','max=nan')):
            with self.assertRaises(ValueError):
                parse_cfg(line)

    def test_reference_six_targets_echo_and_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            ref=make_reference(Path(tmp))
            self.assertEqual(ref.targets((0,0,0)),dict.fromkeys(range(1,7),15.0))
            values=ref.targets((90,2,0))
            text='IK az=90.0 tilt=2.0 twist=0.0 -> '+' '.join(f'n{n}={v:.3f}' for n,v in values.items())
            self.assertLessEqual(max(ref.compare((90,2,0),text,.001)['errors_deg'].values()),.001)
            with self.assertRaises(ValueError):
                ref.compare((0,2,0),text,.001)
            with self.assertRaises(ValueError):
                ref.compare((90,2,0),text.replace('n6=','n5='),.001)
            ref.subject.neutral[1]=[1,1,1]
            with self.assertRaises(ValueError):
                ref.targets((0,0,0))

    def test_actual_parser_ik_no_move_look_common_direction(self):
        cls=next(n for n in ast.parse((ROOT/'firmware/main.py').read_text(encoding='utf-8')).body
                 if isinstance(n,ast.ClassDef) and n.name=='Master')
        fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='handle_line')
        ns={}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'actual-v3-parser','exec'),ns)
        robot=SimpleNamespace(active=63,calls=[],polar=[],look_targets=lambda *args:([15]*6,None))
        robot.send_move=lambda *args:robot.calls.append(args)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            ns['handle_line'](robot,'ik 90 2 0')
        self.assertFalse(robot.calls)
        self.assertIn('n6=15.000',out.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as out:
            ns['handle_line'](robot,'look 90 2 0 500')
        self.assertEqual(robot.calls,[([15000]*6,63,500)])
        self.assertNotIn('OK MOVE',out.getvalue())

    def test_actual_send_move_optimistically_sets_pos_no_ack(self):
        cls=next(n for n in ast.parse((ROOT/'firmware/main.py').read_text(encoding='utf-8')).body
                 if isinstance(n,ast.ClassDef) and n.name=='Master')
        fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='send_move')
        ns={'P':SimpleNamespace(MOVE_FMT='<Hiiiiii'),'struct':struct}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'actual-v3-send','exec'),ns)
        robot=SimpleNamespace(check_ready=lambda *args:None,min_duration_ms=lambda *args:100,
            nodes=[SimpleNamespace(id=n+1,bit=1<<n,target=0,pos=1993) for n in range(6)],move_slot=None,dropped=0)
        ns['send_move'](robot,[15000]*6,63,500)
        self.assertEqual(struct.unpack('<Hiiiiii',robot.move_slot[1]),(500,15000,15000,15000,15000,15000,15000))
        self.assertTrue(all(n.pos==15000 for n in robot.nodes))
        robot.check_ready=lambda *args:'FAULT'
        robot.move_slot=None
        with contextlib.redirect_stdout(io.StringIO()):
            ns['send_move'](robot,[16000]*6,63,500)
        self.assertIsNone(robot.move_slot)


class V3RunTests(unittest.TestCase):
    def exercise(self, wrong_echo=False, repl=False, duplicate=False):
        config=load_config(ROOT/'config/delta-v3-validation-20261014.json')
        config.update(startup_listen_s=.001,queries=6,rate_hz=1000,status_every_queries=2)
        config['serial']['io_timeout_s']=.05
        config['camera']['seconds']=.002
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            ref=make_reference(path)
            class Fake:
                def __init__(self, policy):
                    self.policy=policy
                    self.lines=SimpleNamespace(buffer=b'')
                    self.quarantined=False
                    self.last_rx=b''
                    self.queue=['MicroPython\n>>>'] if repl else []
                    self.commands=[]
                def open(self): pass
                def close(self): pass
                def receive(self, timeout):
                    if not self.queue: return b'',[]
                    line=self.queue.pop(0)
                    self.last_rx=(line+'\n').encode()
                    if repl: self.quarantined=True
                    return self.last_rx,[line]
                def send_query(self, command):
                    self.commands.append(command)
                    self.queue.extend(snapshot() if command=='status' else [f'CFG n{n} '+CFG for n in range(1,7)])
                def send_ik(self,*polar):
                    self.commands.append(('ik',polar))
                    p=tuple(float(f'{v:.3f}') for v in polar)
                    values=ref.targets(p)
                    echo=(p[0]+1,p[1],p[2]) if wrong_echo else p
                    line=f'IK az={echo[0]} tilt={echo[1]} twist={echo[2]} -> '+' '.join(f'n{n}={v:.3f}' for n,v in values.items())
                    self.queue.append(line)
                    if duplicate: self.queue.append(line)
            link=Fake(config['serial'])
            status={'frame_sequence':1,'healthy':True,'capture_alive':True,'face_detected':False,
                    'last_frame_age_seconds':.01,'baseline':{'state':'idle'}}
            class Response(io.StringIO): pass
            with patch('tools.delta_v3_validate.ReadOnlySerial',return_value=link),patch(
                    'tools.delta_v3_validate.urllib.request.urlopen',return_value=Response(__import__('json').dumps(status))):
                result=run(config,path,path/'run.jsonl',path/'summary.json')
            return result,link.commands

    def test_full_run_only_status_cfg_ik_no_fallback_substitute(self):
        result,commands=self.exercise()
        self.assertIsNone(result['error'])
        self.assertEqual(result['synthetic_verified'],6)
        self.assertEqual(result['camera_verified'],0)
        self.assertTrue(all(c in ('status','cfg') if isinstance(c,str) else c[0]=='ik' for c in commands))

    def test_wrong_echo_stops_no_retry(self):
        result,commands=self.exercise(wrong_echo=True)
        self.assertEqual(sum(isinstance(c,tuple) for c in commands),1)

    def test_repl_before_tx_quarantines(self):
        result,commands=self.exercise(repl=True)
        self.assertEqual(commands,[])

    def test_delayed_duplicate_is_not_matched_to_next_query(self):
        result,commands=self.exercise(duplicate=True)
        self.assertIsNotNone(result['error'])
        self.assertEqual(sum(isinstance(c,tuple) for c in commands),1)


if __name__=='__main__':
    unittest.main()
