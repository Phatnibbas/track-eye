import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from delta_bridge.shared_source import SharedSelector, slew_xy
from test_delta_v3 import ROOT, CFG, make_reference, snapshot
from tools.delta_v3_stream import Worker, load_config, unique_usb_device, scaled_polar, direction_delta_deg


def status(seq=1):
    return {'healthy':True,'capture_alive':True,'last_frame_age_seconds':.01,
            'frame_sequence':seq,'uptime_seconds':seq,'face_detected':True,
            'baseline':{'state':'idle'},
            'output_tuning':{'load_error':None,'neutral_state':'idle',
                'calibration':{'gain':{'soft_limit':1.5}}},
            'output_left':{'x':.6,'y':-.3},'output_right':{'x':-.3,'y':.6},
            'fallback':{'sample_id':seq,'config_error':None,
                'config':{'head_sign_validated':False,'head_pose':{'promote_s':.3},
                          'face_position':{'promote_s':.4}},
                'pupil_left':{'valid':True,'quality':{'iris_inside_lid':.18}},
                'pupil_right':{'valid':True,'quality':{'iris_inside_lid':.41}},
                'candidates':{'HEAD_POSE':{'valid':True,'age_s':.01,'target':[.8,.7]},
                              'FACE_POSITION':{'valid':True,'age_s':.01,'target':[.3,.4]},
                              'BODY_POSITION':{'valid':True,'age_s':.01,'target':[1,1]}}}}


class SelectorTests(unittest.TestCase):
    def test_xy_mean_before_angle_and_single_eye(self):
        selector=SharedSelector(.25,.25,True)
        s=status()
        got=selector.select(s,1,0)
        self.assertEqual(got.source,'PUPIL_BOTH_MEAN')
        self.assertAlmostEqual(got.xy[0],.1)
        self.assertAlmostEqual(got.xy[1],.1)
        s=status(2);s['fallback']['pupil_left']['quality']['iris_inside_lid']=1.1
        got=selector.select(s,2,0)
        self.assertEqual(got.source,'PUPIL_RIGHT')
        self.assertAlmostEqual(got.xy[0],-.2)
        self.assertAlmostEqual(got.xy[1],.4)

    def test_head_gate_face_promotion_no_body_or_shadow_replay(self):
        selector=SharedSelector(.25,.25,True)
        s=status();s['face_detected']=False
        s['fallback']['shadow_target_left']=[1,1]
        self.assertIsNone(selector.select(s,1,0).xy)
        s['frame_sequence']=s['fallback']['sample_id']=2
        got=selector.select(s,1.5,0)
        self.assertEqual(got.source,'FACE_POSITION')
        self.assertEqual(got.xy,(.3,.4))
        s['frame_sequence']=s['fallback']['sample_id']=3
        s['fallback']['config']['head_sign_validated']=True
        self.assertIsNone(selector.select(s,2,0).xy)
        s['frame_sequence']=s['fallback']['sample_id']=4
        self.assertEqual(selector.select(s,2.4,0).source,'HEAD_POSE')
        s['frame_sequence']=s['fallback']['sample_id']=5
        s['fallback']['candidates']['HEAD_POSE']['valid']=False
        s['fallback']['candidates']['FACE_POSITION']['valid']=False
        self.assertIsNone(selector.select(s,3,0).xy)

    def test_stale_future_duplicate_restart_and_baseline_no_motion(self):
        for change in (lambda s:s.update(last_frame_age_seconds=.3),
                       lambda s:s.update(last_frame_age_seconds=-.1),
                       lambda s:s['baseline'].update(state='running'),
                       lambda s:s['output_tuning'].update(neutral_state='collecting'),
                       lambda s:s['fallback'].update(sample_id=99)):
            s=status();change(s)
            self.assertIsNone(SharedSelector(.25,.25,True).select(s,1,0).xy)
        selector=SharedSelector(.25,.25,True)
        self.assertIsNotNone(selector.select(status(3),1,0).xy)
        self.assertIsNone(selector.select(status(3),2,0).xy)
        self.assertIsNone(selector.select(status(1),3,0).xy)
        self.assertIsNotNone(selector.select(status(2),4,0).xy)

    def test_slew_bounded_2d_no_source_jump(self):
        xy=slew_xy((0,0),(1,1),.1,2)
        self.assertAlmostEqual((xy[0]**2+xy[1]**2)**.5,.2)
        with self.assertRaises(ValueError):slew_xy((0,0),(1,1),-.1,2)

    def test_duplicate_never_replays_or_cancels_fallback_promotion(self):
        selector=SharedSelector(.25,.25,True)
        s=status();s['face_detected']=False
        self.assertIsNone(selector.select(s,1,0).xy)
        self.assertIsNone(selector.select(s,1.3,0).xy)
        s['frame_sequence']=s['fallback']['sample_id']=2
        self.assertEqual(selector.select(s,1.5,0).source,'FACE_POSITION')

    def test_real_numeric_geometry_not_boolean_confidence(self):
        for bad in (True,False,float('nan'),-.1,1.01,None):
            s=status();s['fallback']['pupil_left']['quality']['iris_inside_lid']=bad
            self.assertEqual(SharedSelector(.25,.25,True).select(s,1,0).source,'PUPIL_RIGHT')
        s=status();s['fallback']['pupil_left']['quality']['iris_inside_lid']=1.0
        self.assertEqual(SharedSelector(.25,.25,True).select(s,1,0).source,'PUPIL_BOTH_MEAN')

    def test_future_fallback_rejected_even_with_http_duration(self):
        s=status();s['face_detected']=False
        s['fallback']['candidates']['FACE_POSITION']['age_s']=-.01
        self.assertIsNone(SharedSelector(.25,.25,True).select(s,1,.1).xy)


class WorkerTests(unittest.TestCase):
    def test_usb_identity_unique_missing_and_ambiguous(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sysroot=root/'sys';sysroot.mkdir()
            device=root/'dev/ttyUSB0';device.parent.mkdir();device.touch()
            port=root/'port';port.mkdir();(port/'idVendor').write_text('1a86');(port/'idProduct').write_text('7523')
            (port/'ttyUSB0').mkdir();(sysroot/'ttyUSB0').symlink_to(port/'ttyUSB0',target_is_directory=True)
            c={'usb_identity':{'vendor':'1a86','product':'7523'},'serial':{'device':str(device)}}
            self.assertTrue(unique_usb_device(c,sysroot))
            (port/'idProduct').write_text('0000')
            self.assertFalse(unique_usb_device(c,sysroot))
            (port/'idProduct').write_text('7523')
            (port/'ttyUSB1').mkdir();(sysroot/'ttyUSB1').symlink_to(port/'ttyUSB1',target_is_directory=True)
            with self.assertRaises(ValueError):unique_usb_device(c,sysroot)

    def setup_worker(self,path,emit=True,fault=False,repl=False,duplicate=False,
                     owner_test=False,move_rejected=False,command_rejected=False):
        cfg=load_config(ROOT/'config/delta-v3-stream-20261014.json')
        if owner_test:cfg['node_state_policy']='observe-only-owner-test'
        refpath=path/'ref';refpath.mkdir()
        ref=make_reference(refpath)
        (refpath/'eyes.txt').write_text('12')
        cfg['reference_dir']=str(refpath)
        cfg['reference_hashes']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in refpath.iterdir() if p.is_file()}
        for name in ('calibration','fallback'):
            p=path/(name+'.json');p.write_text('{}')
            cfg[name+'_file']=str(p);cfg[name+'_sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
        cfg['state_dir']=str(path/'state')
        cfg.update(startup_listen_s=.01,status_period_s=.1,cfg_period_s=30,first_duration_ms=10,
                   first_timeout_s=1)
        cfg['serial']['io_timeout_s']=.1
        class Fake:
            quarantined=False
            last_rx=b''
            def __init__(self):
                self.queue=['MicroPython >>>'] if repl else []
                self.commands=[]
                self.lines=type('Lines',(),{'buffer':b''})()
                self.positions=None
                self.look_times=[]
            def open(self):pass
            def close(self):pass
            def receive(self,timeout):
                if not self.queue:
                    time.sleep(min(timeout,.001));return b'',[]
                line=self.queue.pop(0)
                if repl:self.quarantined=True
                return (line+'\n').encode(),[line]
            def send_query(self,cmd):
                self.commands.append(cmd)
                if cmd=='status':
                    lines=snapshot()
                    if self.positions is not None:
                        lines=[lines[0]]+[f'STAT n{n} ON IDLE err=NONE homed=1 sw=0 pos={self.positions[n]:.3f} target={self.positions[n]:.3f}' for n in range(1,7)]
                    if fault:lines[0]=lines[0].replace('False','True')
                    self.queue.extend(lines)
                else:self.queue.extend(f'CFG n{n} '+CFG for n in range(1,7))
            def _write_line(self,cmd):
                self.commands.append(cmd)
                if cmd=='clear':self.queue.append('OK CLEAR')
            def send_ik(self,*polar):self.commands.append(('ik',polar));self.reply(polar)
            def send_look(self,polar,ms):
                self.look_times.append(time.monotonic())
                self.commands.append(('look',polar,ms))
                if command_rejected:self.queue.append('ERR look: mắt 1 chưa calib')
                else:self.reply(polar)
                if move_rejected:self.queue.append('ERR move: hệ thống đang FAULT')
                if fault:
                    self.queue.extend(['ERR n4 OFFLINE (không trả lời)',
                                       'EVT n6 BOOT fw=3 reset=POWER_ON','FAULT n6 mất vị trí'])
                if not command_rejected:
                    self.positions=ref.targets(tuple(float(f'{v:.3f}') for v in polar))
            def reply(self,polar):
                p=tuple(float(f'{v:.3f}') for v in polar)
                motors=ref.targets(p)
                line=f'IK az={p[0]} tilt={p[1]} twist={p[2]} -> '+' '.join(f'n{n}={v:.3f}' for n,v in motors.items())
                self.queue.append(line)
                if duplicate:self.queue.append(line)
        return Worker(cfg,emit),Fake()

    def run_worker(self,path,**flags):
        worker,link=self.setup_worker(path,**flags)
        seq=0
        def http(*args,**kwargs):
            nonlocal seq
            seq+=1
            return io.StringIO(json.dumps(status(seq)))
        with patch('tools.delta_v3_stream.TrialSerial',return_value=link),patch(
                'tools.delta_v3_stream.unique_usb_device',return_value=True),patch(
                'tools.delta_v3_stream.urllib.request.urlopen',side_effect=http):
            worker.run(.35)
        for handler in worker.log.handlers:handler.close()
        return worker,link

    def test_first_live_target_slow_no_neutral_clear_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker,link=self.run_worker(Path(tmp))
            looks=[c for c in link.commands if isinstance(c,tuple) and c[0]=='look']
            self.assertTrue(looks)
            self.assertGreater(looks[0][1][1],0)
            self.assertEqual(looks[0][2],10)
            self.assertFalse(worker.latch.exists())
            self.assertGreaterEqual(len(looks),2)
            self.assertTrue(all(b-a>=1/worker.c['poll_hz']-.001 for a,b in zip(link.look_times,link.look_times[1:])))
            self.assertTrue(all(c in ('status','cfg') if isinstance(c,str) else c[0] in ('ik','look') for c in link.commands))

    def test_fault_or_repl_never_moves(self):
        for flag in ('fault','repl','duplicate'):
            with tempfile.TemporaryDirectory() as tmp:
                worker,link=self.run_worker(Path(tmp),**{flag:True})
                self.assertFalse(any(isinstance(c,tuple) and c[0]=='look' for c in link.commands))
                if flag!='fault':self.assertTrue(worker.latch.exists())

    def test_latch_survives_restart_prevents_any_serial_tx(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker,link=self.setup_worker(Path(tmp))
            worker.latch.write_text('{"fault":"test"}')
            with patch('tools.delta_v3_stream.TrialSerial',return_value=link):worker.run(.1)
            self.assertEqual(link.commands,[])
            for handler in worker.log.handlers:handler.close()

    def test_ik_mode_never_sends_look(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker,link=self.run_worker(Path(tmp),emit=False)
            self.assertFalse(any(isinstance(c,tuple) and c[0]=='look' for c in link.commands))

    def test_no_source_keeps_process_alive_and_sends_no_neutral(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker,link=self.setup_worker(Path(tmp))
            seq=0
            def http(*args,**kwargs):
                nonlocal seq
                seq+=1;s=status(seq);s['face_detected']=False
                for c in s['fallback']['candidates'].values():c['valid']=False
                return io.StringIO(json.dumps(s))
            with patch('tools.delta_v3_stream.TrialSerial',return_value=link),patch(
                    'tools.delta_v3_stream.unique_usb_device',return_value=True),patch(
                    'tools.delta_v3_stream.urllib.request.urlopen',side_effect=http):
                worker.run(.35)
            self.assertFalse(any(isinstance(c,tuple) and c[0]=='look' for c in link.commands))
            self.assertFalse(worker.latch.exists())
            for h in worker.log.handlers:h.close()

    def test_owner_test_sends_despite_node_fault_without_status_or_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker,link=self.run_worker(Path(tmp),owner_test=True,fault=True,move_rejected=True)
            looks=[c for c in link.commands if isinstance(c,tuple) and c[0]=='look']
            self.assertGreaterEqual(len(looks),2)
            self.assertNotIn('status',link.commands)
            self.assertFalse(worker.latch.exists())
            self.assertEqual(worker.counts['master_move_rejections'],len(looks))
            self.assertEqual(worker.counts['echo'],len(looks))

    def test_owner_test_command_rejections_counted_not_motor_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker,link=self.run_worker(Path(tmp),owner_test=True,command_rejected=True)
            self.assertGreaterEqual(worker.counts['look'],2)
            self.assertEqual(worker.counts['echo'],0)
            self.assertEqual(worker.counts['master_command_rejections'],worker.counts['look'])
            self.assertFalse(worker.latch.exists())

    def test_owner_test_still_blocks_repl_and_duplicate_protocol(self):
        for flag in ('repl','duplicate'):
            with tempfile.TemporaryDirectory() as tmp:
                worker,link=self.run_worker(Path(tmp),owner_test=True,**{flag:True})
                self.assertTrue(worker.latch.exists())
                self.assertEqual(worker.counts['look'],0)

    def test_only_prequery_known_diagnostic_tail_can_be_discarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker,link=self.setup_worker(Path(tmp),owner_test=True)
            worker.link=link
            link.lines.buffer=bytearray(b'FAULT n6 old diagnostic')
            worker.discard_startup_diagnostic()
            self.assertEqual(link.lines.buffer,bytearray())
            for tail in (b'IK az=0',b'>>> ',b'unknown',b'FAULT testIK az=0'):
                link.lines.buffer=bytearray(tail)
                with self.assertRaises(ValueError):worker.discard_startup_diagnostic()
            link.lines.buffer=bytearray(b'FAULT old')
            worker.pending=(0,0,0)
            with self.assertRaises(ValueError):worker.discard_startup_diagnostic()
            for h in worker.log.handlers:h.close()

    def test_deadband_uses_last_sent_not_last_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker,link=self.setup_worker(Path(tmp),owner_test=True)
            worker.c['deadband_deg']=.2
            worker.link=link
            worker.ever_armed=True;worker.last_xy=(0,0);worker.last_polar=(0,0,0)
            worker.last_status_at=worker.last_cfg_at=time.monotonic()
            worker.ref=make_reference(Path(tmp)/'ref')
            for seq,value in enumerate((.03,.06,.09),1):
                s=status(seq);s['output_left']=s['output_right']={'x':value*1.5,'y':0}
                with patch('tools.delta_v3_stream.urllib.request.urlopen',return_value=io.StringIO(json.dumps(s))):
                    worker.step()
            self.assertEqual(worker.counts['look'],0)
            s=status(4);s['output_left']=s['output_right']={'x':.16*1.5,'y':0}
            with patch('tools.delta_v3_stream.urllib.request.urlopen',return_value=io.StringIO(json.dumps(s))):worker.step()
            self.assertEqual(worker.counts['look'],1)
            for h in worker.log.handlers:h.close()

    def test_auto_clear_once_ack_cooldown_budget_no_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker,link=self.setup_worker(Path(tmp),owner_test=True)
            worker.link=link
            worker.c['clear_policy']={'enabled':True,'cooldown_s':5,'max_consecutive':2}
            worker.observe(b'FAULT test\n',['FAULT test'])
            worker.service_clear()
            self.assertEqual(link.commands,['clear'])
            self.assertEqual(worker.counts['clear_ack'],1)
            worker.observe(b'FAULT test\n',['FAULT test'])
            worker.service_clear()
            self.assertEqual(link.commands,['clear'])
            worker.last_clear_at-=6;worker.last_tx_started-=6;worker.service_clear()
            self.assertEqual(link.commands,['clear','clear'])
            worker.last_clear_at-=6;worker.last_tx_started-=6;worker.observe(b'FAULT test\n',['FAULT test']);worker.service_clear()
            self.assertEqual(link.commands,['clear','clear'])
            for h in worker.log.handlers:h.close()

    def test_math_rejection_not_cleared_or_locally_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker,link=self.setup_worker(Path(tmp),owner_test=True,command_rejected=True)
            worker.link=link
            worker.c['clear_policy']['enabled']=True
            worker.ref=make_reference(Path(tmp)/'ref')
            self.assertFalse(worker.exchange((0,20,0),True))
            self.assertEqual(worker.counts['look'],1)
            self.assertIsNone(worker.pending_clear)
            self.assertNotIn('clear',link.commands)
            for h in worker.log.handlers:h.close()

    def test_owner_requested_rate_scale_cap_and_deadband(self):
        c=load_config(ROOT/'config/delta-v3-stream-owner-test-20261014.json')
        self.assertEqual(c['poll_hz'],5)
        self.assertEqual(c['deadband_deg'],1)
        self.assertEqual(c['tilt_multiplier'],10)
        self.assertEqual(c['output_tilt_cap_deg'],15)
        with tempfile.TemporaryDirectory() as tmp:
            worker,link=self.setup_worker(Path(tmp),owner_test=True)
            worker.c.update(tilt_multiplier=10,output_tilt_cap_deg=15,poll_hz=5)
            worker.link=link;worker.last_cfg_at=time.monotonic()
            worker.ref=make_reference(Path(tmp)/'ref')
            for seq,x,wanted in ((1,.3,6),(2,.9,15)):
                # Separate startup target cases avoid waiting for first motion.
                worker.ever_armed=False;worker.first_target_at=None;worker.last_tx_started=None
                s=status(seq);s['output_left']=s['output_right']={'x':x*1.5,'y':0}
                with patch('tools.delta_v3_stream.urllib.request.urlopen',return_value=io.StringIO(json.dumps(s))):
                    worker.step()
                look=next(c for c in reversed(link.commands) if isinstance(c,tuple) and c[0]=='look')
                self.assertAlmostEqual(look[1][1],wanted)
                self.assertEqual(look[1][0],0)
            for h in worker.log.handlers:h.close()

    def test_angular_deadband_after_gain_wrap_and_saturation(self):
        c=load_config(ROOT/'config/delta-v3-stream-owner-test-20261014.json')
        from delta_bridge.core import Mapping
        m=Mapping(**c['mapping'])
        self.assertAlmostEqual(scaled_polar(m,(.3,0),10,15)[1],6)
        self.assertEqual(scaled_polar(m,(1,0),10,15)[1],15)
        self.assertEqual(direction_delta_deg((0,15,0),(0,15,0)),0)
        self.assertLess(direction_delta_deg((359,10,0),(1,10,0)),1)
        self.assertAlmostEqual(direction_delta_deg((0,5,0),(0,5.8,0)),.8)
        self.assertAlmostEqual(direction_delta_deg((0,5,0),(0,6.2,0)),1.2)

    def test_clear_timeout_not_retried_and_geometry_error_not_cleared(self):
        with tempfile.TemporaryDirectory() as tmp:
            worker,link=self.setup_worker(Path(tmp),owner_test=True)
            worker.link=link;worker.c['clear_policy']['enabled']=True
            worker.observe(b'ERR look: outside travel\n',['ERR look: outside travel'])
            self.assertIsNone(worker.pending_clear)
            worker.observe(b'ERR move: n4 offline\n',['ERR move: n4 offline'])
            self.assertIsNone(worker.pending_clear)
            worker.observe(b'FAULT motor error\n',['FAULT motor error'])
            link._write_line=lambda cmd:link.commands.append(cmd)  # No ACK.
            try:
                with self.assertRaises(TimeoutError):worker.service_clear()
                self.assertEqual(link.commands,['clear'])
            finally:
                for h in worker.log.handlers:h.close()


if __name__=='__main__':unittest.main()
