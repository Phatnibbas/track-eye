"""Negative tests exercise actual shared-camera-trial dispatch path."""
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from delta_bridge.v3 import V3Snapshot, motion_gate
from test_delta_v3 import make_reference, snapshot, CFG, ROOT
from tools.delta_v3_camera_trial import load_trial, run, TrialSerial, neutral_reported


class GateTests(unittest.TestCase):
    def test_current_home_to_saved_neutral_is_not_small_tilt(self):
        state=V3Snapshot((1,2),0,1)
        for line in snapshot(): state.consume(line,1)
        with self.assertRaises(ValueError):
            motion_gate(state,1,1,dict.fromkeys(range(1,7),15),
                        {n:{'min':2,'max':30} for n in range(1,7)},2)

    def test_stale_fault_and_unknown_node_block(self):
        state=V3Snapshot((1,2),0,1)
        for line in snapshot(): state.consume(line,1)
        limits={n:{'min':2,'max':30} for n in range(1,7)}
        with self.assertRaises(ValueError):
            motion_gate(state,3,1,dict.fromkeys(range(1,7),2.1),limits,2)
        with self.assertRaises(ValueError):
            motion_gate(state,1,1,{1:2.1},limits,2)
        state.consume('FAULT test',1)
        with self.assertRaises(ValueError):
            motion_gate(state,1,1,dict.fromkeys(range(1,7),2.1),limits,2)

    def test_typed_look_rejects_nonfinite_duration_and_injection(self):
        link=TrialSerial(SimpleNamespace(max_line_bytes=2048))
        with patch.object(link,'_write_line') as writer:
            link.send_look((90,2,0),500)
            writer.assert_called_once_with('look 90.000 2.000 0.000 500')
            for polar,ms in (((float('nan'),0,0),500),((0,0,0),0),((0,0,0),65536),
                             (('0\nhome',0,0),500),((0,0,0),True)):
                with self.assertRaises(ValueError): link.send_look(polar,ms)

    def test_neutral_must_be_idle_position_not_just_target(self):
        s=V3Snapshot((1,2),0,1)
        for line in snapshot():
            s.consume(line.replace('target=0.000','target=15.000'),1)
        self.assertFalse(neutral_reported(s,1,1,dict.fromkeys(range(1,7),15),.1))
        for node in s.nodes.values(): node['pos']=15
        self.assertTrue(neutral_reported(s,1,1,dict.fromkeys(range(1,7),15),.1))
        s.nodes[1]['state']='MOVING'
        self.assertFalse(neutral_reported(s,1,1,dict.fromkeys(range(1,7),15),.1))


class TrialRunTests(unittest.TestCase):
    def exercise(self, home=False, fault=False, stale=False, echo_wrong=False, duplicate=False,
                 calibration_changed=False, noface=False,approach=False,never_arrive=False,
                 camera_lost_after_ik=False,newer_target=False):
        config=load_trial(ROOT/'config/delta-v3-camera-trial-20261014.json')
        config.update(seconds=.03,poll_hz=10)
        config['serial']['io_timeout_s']=.05
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            ref=make_reference(path)
            cal=path/'camera-calibration.json'
            cal.write_text('{}')
            config['expected_calibration_sha256']=hashlib.sha256(cal.read_bytes()).hexdigest()
            if calibration_changed: cal.write_text('{"changed":true}')
            class Fake:
                def __init__(self):
                    self.queue=[];self.commands=[];self.quarantined=False;self.last_rx=b''
                    self.lines=SimpleNamespace(buffer=b'')
                    self.arrived=False
                def open(self): pass
                def close(self): pass
                def receive(self,timeout):
                    if not self.queue: return b'',[]
                    line=self.queue.pop(0); self.last_rx=(line+'\n').encode()
                    return self.last_rx,[line]
                def send_query(self,cmd):
                    self.commands.append(cmd)
                    if cmd=='cfg': self.queue.extend(f'CFG n{n} '+CFG for n in range(1,7))
                    else:
                        lines=snapshot()
                        if not home or self.arrived: lines=[s.replace('pos=1.993 target=0.000','pos=15.000 target=15.000') for s in lines]
                        if fault: lines[0]=lines[0].replace('fault=False','fault=True')
                        self.queue.extend(lines)
                def reply(self,polar):
                    p=tuple(float(f'{v:.3f}') for v in polar)
                    motors=ref.targets(p)
                    if echo_wrong:p=(p[0]+1,p[1],p[2])
                    text=f'IK az={p[0]} tilt={p[1]} twist={p[2]} -> '+' '.join(f'n{n}={v:.3f}' for n,v in motors.items())
                    self.queue.append(text)
                    if duplicate:self.queue.append(text)
                def send_ik(self,*polar):self.commands.append(('ik',polar));self.reply(polar)
                def send_look(self,polar,ms):
                    self.commands.append(('look',polar,ms));self.reply(polar)
                    if approach and not never_arrive:self.arrived=True
            link=Fake()
            status={'frame_sequence':1,'healthy':True,'capture_alive':True,'face_detected':not noface,
                    'last_frame_age_seconds':1.0 if stale else .01,'baseline':{'state':'idle'},
                    'output_left':{'x':0,'y':0},'output_tuning':{'calibration':{'gain':{'soft_limit':1.5}}}}
            requests=0
            def http(*args,**kwargs):
                nonlocal requests
                requests+=1
                data=dict(status)
                if requests>1 and camera_lost_after_ik:
                    data['face_detected']=False
                if requests>1 and newer_target:
                    data['frame_sequence']=2
                    data['output_left']={'x':.1,'y':0}
                return io.StringIO(json.dumps(data))
            with patch('tools.delta_v3_camera_trial.TrialSerial',return_value=link),patch(
                    'tools.delta_v3_camera_trial.urllib.request.urlopen',side_effect=http):
                a=dict(duration_ms=1,timeout_s=.2,position_tolerance_deg=.1,
                       max_motor_step_deg=15,status_poll_hz=1000,stable_snapshots=2) if approach else None
                result=run(config,path,cal,path/'trial.jsonl',path/'summary.json',a)
            return result,link.commands

    def test_home_jump_blocks_before_any_look_or_ik(self):
        result,commands=self.exercise(home=True)
        self.assertFalse(any(isinstance(c,tuple) for c in commands))

    def test_fault_blocks_before_cfg_or_motion(self):
        result,commands=self.exercise(fault=True)
        self.assertEqual(commands,['status'])

    def test_full_approved_trial_from_neutral_only(self):
        result,commands=self.exercise()
        self.assertIsNone(result['error'])
        self.assertEqual(result['look_sent'],1)
        self.assertEqual(result['look_echo_verified'],1)
        self.assertTrue(all(c in ('status','cfg') if isinstance(c,str) else c[0] in ('ik','look') for c in commands))

    def test_nonusable_camera_never_replaced_by_neutral(self):
        for flags in ({'stale':True},{'noface':True}):
            result,commands=self.exercise(**flags)
            self.assertEqual(result['look_sent'],0)
            self.assertFalse(any(isinstance(c,tuple) for c in commands))

    def test_wrong_echo_duplicate_or_changed_calibration_no_look(self):
        for flags in ({'echo_wrong':True},{'duplicate':True},{'calibration_changed':True}):
            result,commands=self.exercise(**flags)
            self.assertIsNotNone(result['error'])
            self.assertEqual(result['look_sent'],0)

    def test_approved_approach_once_then_trial(self):
        result,commands=self.exercise(home=True,approach=True)
        self.assertIsNone(result['error'])
        self.assertEqual(result['neutral_look_sent'],1)
        self.assertTrue(result['neutral_reported_complete'])
        self.assertEqual(sum(isinstance(c,tuple) and c[0]=='look' and c[2]==1 for c in commands),1)
        self.assertEqual(result['look_sent'],1)

    def test_no_reported_arrival_never_runs_camera_no_retry(self):
        result,commands=self.exercise(home=True,approach=True,never_arrive=True)
        self.assertEqual(result['neutral_look_sent'],1)
        self.assertFalse(result['neutral_reported_complete'])
        self.assertEqual(result['look_sent'],0)

    def test_lost_camera_after_ik_disarms_without_look(self):
        result,commands=self.exercise(camera_lost_after_ik=True)
        self.assertEqual(result['look_sent'],0)
        self.assertEqual(sum(isinstance(c,tuple) and c[0]=='ik' for c in commands),1)

    def test_latest_frame_used_not_previous_checked_target(self):
        result,commands=self.exercise(newer_target=True)
        self.assertIsNone(result['error'])
        look=next(c for c in commands if isinstance(c,tuple) and c[0]=='look')
        self.assertGreater(look[1][1],0)
        self.assertEqual(result['look_sent'],1)


if __name__=='__main__': unittest.main()
