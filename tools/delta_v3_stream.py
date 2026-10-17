"""Persistent Pi-side owner-approved shared-target sender; fail-closed faults.

No camera ownership, firmware recovery, neutral approach or home. Explicit owner
test profile can issue bounded CLEAR on robot faults, not transport/math errors.
starts on boot; first live target moves slowly, without a neutral command.
Persistent fault latch needs manual review.
"""
import argparse
from collections import Counter
import hashlib
import json
import logging
import math
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path, PurePosixPath
import signal
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from delta_bridge.config import SerialPolicy, _read, exact_keys, positive
from delta_bridge.core import Mapping, finite_number
from delta_bridge.shared_source import SharedSelector, slew_xy
from delta_bridge.v3 import V3Reference, V3Snapshot, motion_gate
from delta_bridge.serial_transport import ReadOnlySerial, SerialProtocolError
from tools.delta_protocol_audit import drain_diagnostics
from tools.delta_v3_camera_trial import TrialSerial


def scaled_polar(mapping, xy, multiplier, cap_deg):
    az, tilt, twist = mapping.polar(*xy)
    return az, min(cap_deg, tilt * multiplier), twist


def direction_delta_deg(a, b):
    """Distance of tilt vectors in degrees; azimuth wraps without discontinuity."""
    ax, ay = a[1]*math.cos(math.radians(a[0])), a[1]*math.sin(math.radians(a[0]))
    bx, by = b[1]*math.cos(math.radians(b[0])), b[1]*math.sin(math.radians(b[0]))
    return math.hypot(ax-bx, ay-by)


def load_config(path):
    c = _read(path)
    exact_keys(c, ('schema_version', 'serial', 'usb_identity', 'expected_eyes', 'expected_vergence_deg',
                  'snapshot_window_s', 'status_max_age_s', 'status_period_s', 'cfg_period_s', 'poll_hz',
                  'startup_listen_s', 'frame_max_age_s', 'candidate_max_age_s', 'require_inside_lid',
                  'slew_per_s', 'max_motor_step_deg', 'first_motor_step_deg', 'first_duration_ms',
                  'first_timeout_s', 'numeric_tolerance_deg',
                  'mapping', 'status_url', 'state_dir', 'calibration_file', 'calibration_sha256',
                  'fallback_file', 'fallback_sha256', 'reference_dir', 'reference_hashes',
                  'log_max_bytes', 'log_backup_count', 'node_state_policy',
                  'deadband_deg', 'clear_policy', 'tilt_multiplier', 'output_tilt_cap_deg'), 'stream config')
    if type(c['schema_version']) is not int or c['schema_version'] != 1:
        raise ValueError('unsupported stream schema')
    if c['node_state_policy'] not in ('gate', 'observe-only-owner-test'):
        raise ValueError('explicit node state policy required')
    if not finite_number(c['deadband_deg']) or not 0 <= c['deadband_deg'] <= 2*c['output_tilt_cap_deg']:
        raise ValueError('explicit finite angular deadband required')
    positive(c['tilt_multiplier'],'tilt multiplier')
    positive(c['output_tilt_cap_deg'],'output tilt cap')
    exact_keys(c['clear_policy'], ('enabled','cooldown_s','max_consecutive'), 'clear policy')
    if type(c['clear_policy']['enabled']) is not bool:
        raise ValueError('explicit CLEAR enablement required')
    positive(c['clear_policy']['cooldown_s'], 'clear cooldown')
    if type(c['clear_policy']['max_consecutive']) is not int or c['clear_policy']['max_consecutive'] <= 0:
        raise ValueError('explicit bounded consecutive CLEAR budget required')
    if c['clear_policy']['enabled'] and c['node_state_policy'] != 'observe-only-owner-test':
        raise ValueError('automatic CLEAR is only allowed in explicit owner test profile')
    exact_keys(c['serial'], ('device','baud','io_timeout_s','max_line_bytes'), 'serial')
    SerialPolicy(**c['serial'])
    V3Snapshot(c['expected_eyes'], c['expected_vergence_deg'], c['snapshot_window_s'])
    exact_keys(c['usb_identity'], ('vendor','product'), 'USB identity')
    for value in c['usb_identity'].values():
        if not isinstance(value,str) or len(value)!=4 or any(ch not in '0123456789abcdef' for ch in value):
            raise ValueError('explicit USB VID/PID required')
    exact_keys(c['mapping'], ('slot','max_tilt_deg','az_offset_deg','x_sign','y_sign','twist_deg','duration_ms'), 'mapping')
    Mapping(**c['mapping'])
    if c['mapping']['slot'] != 'left':
        raise ValueError('mapping slot is compatibility-only; shared selector owns both slots')
    for key in ('status_max_age_s','status_period_s','cfg_period_s','poll_hz','startup_listen_s',
                'frame_max_age_s','candidate_max_age_s','slew_per_s','max_motor_step_deg',
                'first_motor_step_deg','first_timeout_s','numeric_tolerance_deg'):
        positive(c[key],key)
    if (type(c['first_duration_ms']) is not int or not 1 <= c['first_duration_ms'] <= 65535
            or c['first_timeout_s'] <= c['first_duration_ms']/1000):
        raise ValueError('explicit valid slow first-target timing required')
    if c['poll_hz']>15 or c['status_period_s']>=c['status_max_age_s'] or c['frame_max_age_s']>=c['status_max_age_s']:
        raise ValueError('invalid rate/freshness policy')
    SharedSelector(c['frame_max_age_s'],c['candidate_max_age_s'],c['require_inside_lid'])
    for key in ('log_max_bytes','log_backup_count'):
        if type(c[key]) is not int or c[key]<=0:
            raise ValueError('explicit positive log retention required')
    if not isinstance(c['status_url'],str) or not c['status_url'].startswith('http://127.0.0.1:'):
        raise ValueError('explicit loopback status URL required')
    for key in ('state_dir','calibration_file','fallback_file','reference_dir'):
        if not isinstance(c[key],str) or not (Path(c[key]).is_absolute() or PurePosixPath(c[key]).is_absolute()):
            raise ValueError('absolute deployment paths required: '+key)
    exact_keys(c['reference_hashes'],('main.py','proto3.py','spm_ik.py','neutral3.txt','eyes.txt'),'reference hashes')
    for h in [c['calibration_sha256'],c['fallback_sha256'],*c['reference_hashes'].values()]:
        if not isinstance(h,str) or len(h)!=64 or any(ch not in '0123456789abcdef' for ch in h):
            raise ValueError('explicit source/state SHA256 required')
    return c


def verify_files(c):
    paths={Path(c['calibration_file']):c['calibration_sha256'],Path(c['fallback_file']):c['fallback_sha256']}
    paths.update({Path(c['reference_dir'])/p:h for p,h in c['reference_hashes'].items()})
    for path, expected in paths.items():
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError('deployment/state checksum changed: '+str(path))


def unique_usb_device(c, sys_root=Path('/sys/class/tty')):
    matches=[]
    for tty in sys_root.glob('ttyUSB*'):
        for ancestor in (tty.resolve(),*tty.resolve().parents):
            vendor,product=ancestor/'idVendor',ancestor/'idProduct'
            if vendor.is_file() and product.is_file():
                if (vendor.read_text().strip(),product.read_text().strip()) == (
                        c['usb_identity']['vendor'],c['usb_identity']['product']):
                    matches.append(tty.name)
                break
    if len(matches)>1:
        raise ValueError('ambiguous CH340 identity; no serial open')
    device=Path(c['serial']['device'])
    if not matches or not device.exists():
        return False
    if device.resolve().name!=matches[0]:
        raise ValueError('configured port does not match unique expected USB identity')
    return True


class Worker:
    def __init__(self,c,emit):
        self.c=c
        self.emit=emit
        self.link=None
        self.ref=V3Reference(c['reference_dir'],c['expected_eyes'],c['expected_vergence_deg'])
        self.robot=V3Snapshot(c['expected_eyes'],c['expected_vergence_deg'],c['snapshot_window_s'])
        self.selector=SharedSelector(c['frame_max_age_s'],c['candidate_max_age_s'],c['require_inside_lid'])
        self.map=Mapping(**c['mapping'])
        self.stopping=False
        self.counts=Counter()
        self.last_xy=(0.0,0.0)
        self.last_polar=None
        self.last_sent_at=None
        self.last_tx_started=None
        self.last_cfg_at=self.last_status_at=0
        self.pending=None
        self.pending_match=None
        self.ever_armed=False
        self.node_gate=c['node_state_policy']=='gate'
        self.pending_rejected=None
        self.pending_move_rejected=False
        self.pending_clear=None
        self.clear_ack=False
        self.last_clear_at=None
        self.consecutive_clears=0
        self.force_fresh_target=False
        self.first_target_at=None
        self.state_dir=Path(c['state_dir'])
        self.state_dir.mkdir(parents=True,exist_ok=True)
        self.latch=self.state_dir/'fault-latch.json'
        self.view={'phase':'STARTING','source':'NONE','emit_enabled':emit,'look_sent':0,'echo_verified':0,
                   'node_state_policy':c['node_state_policy'],
                   'target_rate_hz':c['poll_hz'], 'max_tilt_deg':c['output_tilt_cap_deg'],
                   'tilt_multiplier':c['tilt_multiplier'],
                   'deadband_deg':c['deadband_deg'], 'auto_clear_policy':c['clear_policy'],
                   'motor_delivery_claim':False,
                   'head_axis_gate':'requires production head_sign_validated=true',
                   'loss_policy':'no new movement; last command may finish/hold; no firmware Pi watchdog'}
        self.log=logging.getLogger('delta-stream-'+str(id(self)))
        self.log.setLevel(logging.INFO)
        self.log.propagate=False
        handler=RotatingFileHandler(self.state_dir/'tx-rx.jsonl',maxBytes=c['log_max_bytes'],backupCount=c['log_backup_count'],encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(message)s'))
        self.log.addHandler(handler)

    def record(self,**fields):
        self.log.info(json.dumps({'monotonic_s':time.monotonic(),**fields},ensure_ascii=False,allow_nan=False))

    def publish(self,phase=None,**fields):
        old=(self.view.get('phase'),self.view.get('source'))
        if phase is not None:self.view['phase']=phase
        self.view.update(fields)
        self.view.update(monotonic_s=time.monotonic(),look_sent=self.counts['look'],echo_verified=self.counts['echo'],
                         ik_verified=self.counts['ik'],counters=dict(self.counts))
        temp=self.state_dir/'status.pending'
        temp.write_text(json.dumps(self.view,indent=2,ensure_ascii=False),encoding='utf-8')
        temp.replace(self.state_dir/'status.json')
        if old!=(self.view.get('phase'),self.view.get('source')):
            print(json.dumps({k:self.view.get(k) for k in ('phase','source','reason','look_sent')},ensure_ascii=False),flush=True)

    def fault(self,error):
        data={'error':str(error),'monotonic_s':time.monotonic(),'automatic_recovery':False}
        tmp=self.state_dir/'fault-latch.pending'
        tmp.write_text(json.dumps(data,indent=2),encoding='utf-8')
        tmp.replace(self.latch)
        self.record(fault=data)
        self.publish('FAULT_LATCHED',source='NONE',reason=str(error))

    def observe(self,raw,lines):
        if raw:self.record(rx_hex=raw.hex(),lines=lines)
        for line in lines:
            if line.startswith('CFG '):self.ref.apply_cfg(line)
            if self.node_gate:
                self.robot.consume(line,time.monotonic())
            elif line.startswith(('STAT','ENC','PWR')):
                self.view['last_robot_observation']=line
            if line.startswith(('FAULT','ERR','WARN STOP')) or (line.startswith('EVT') and 'BOOT' in line):
                if self.node_gate:
                    raise SerialProtocolError('robot/protocol diagnostic: '+line)
                self.counts['robot_diagnostics']+=1
                self.view['last_robot_diagnostic']=line
                self.record(robot_diagnostic=line,blocks_host_tx=False)
                if line.startswith('ERR move:'):
                    self.counts['master_move_rejections']+=1
                    self.pending_move_rejected=True
                clearable=(line.startswith('FAULT ') or re.match(r'^ERR n\d+ ',line) is not None
                           or (line.startswith('ERR move:') and any(reason in line for reason in
                               ('FAULT','đang ERROR'))))
                if clearable and self.c['clear_policy']['enabled']:
                    self.pending_clear=line
                if self.pending is not None and line.startswith(('ERR ik:', 'ERR look:', 'ERR sai tham số', 'ERR lệnh không rõ')):
                    self.pending_rejected=line
            if line == 'OK CLEAR':
                self.clear_ack=True
                self.counts['clear_ack']+=1
            if 'IK az=' in line:
                if self.pending is None or not line.startswith('IK ') or self.pending_match is not None:
                    raise SerialProtocolError('unsolicited/merged/duplicate IK')
                self.pending_match=self.ref.compare(self.pending,line,self.c['numeric_tolerance_deg'])

    def receive(self,timeout):
        raw,lines=self.link.receive(timeout)
        self.observe(raw,lines)
        if self.link.quarantined:raise SerialProtocolError('boot/REPL/traceback; no auto recovery')

    def drain(self):
        drain_diagnostics(self.link,self.c['serial']['io_timeout_s'],self.observe)

    def discard_startup_diagnostic(self):
        """Only a pre-query diagnostic tail from a previously closed session.

        Do not repair it, feed it to the reply parser, or discard any outstanding
        IK/boot/REPL bytes. New transactions still need standalone strict echoes.
        """
        tail=bytes(self.link.lines.buffer)
        if not tail:return
        # A prior process can be terminated mid-response; a known trailing
        # motor-list fragment is stale RX, not an outstanding new transaction.
        ik_suffix = re.fullmatch(rb'[0-9.]+ -> (?:n[1-6]=[+\-0-9.]+ ?)+', tail) is not None
        if self.node_gate or self.pending is not None or not (ik_suffix or tail.startswith((b'FAULT ',b'STAT ',b'ERR ',b'EVT ',b'ENC ',b'PWR '))):
            raise SerialProtocolError('unrecognized partial startup input')
        if any(t in tail for t in (b'IK az=',b'>>>',b'Traceback',b'MicroPython')):
            raise SerialProtocolError('startup partial reply/REPL must not be discarded')
        self.record(discarded_startup_diagnostic_hex=tail.hex(),reason='previous session tail; no outstanding query',
                    treated_as_valid_response=False)
        self.link.lines.buffer.clear()
        self.counts['discarded_startup_diagnostic']+=1

    def query_status(self):
        self.drain()
        self.robot.reset()
        self.link.send_query('status')
        self.record(tx='status',motion_tx=False)
        end=time.monotonic()+self.c['serial']['io_timeout_s']
        while not self.stopping and time.monotonic()<end:
            self.receive(max(0,end-time.monotonic()))
            if self.robot.complete_at is not None:
                self.drain()
                self.last_status_at=time.monotonic()
                self.counts['status']+=1
                self.record(snapshot=self.robot.nodes,fault=self.robot.fault)
                return
        if not self.stopping:raise TimeoutError('no complete fresh robot status')

    def service_clear(self):
        """Serialize owner-approved CLEAR once per observed fault, with cooldown.

        Never issue HOME or reset, retry a rejected stale target, or clear a USB
        fault latch. Budget bounds persistent error loops; LOOK test can continue.
        """
        if self.pending_clear is None or not self.c['clear_policy']['enabled']:return
        now=time.monotonic()
        if self.last_clear_at is not None and now-self.last_clear_at < self.c['clear_policy']['cooldown_s']:return
        if self.last_tx_started is not None and now-self.last_tx_started < 1/self.c['poll_hz']:return
        if self.consecutive_clears>=self.c['clear_policy']['max_consecutive']:
            self.publish('CLEAR_BUDGET_EXHAUSTED',reason='persistent robot errors; no repeated clear loop',
                         last_clear_reason=self.pending_clear)
            self.pending_clear=None
            return
        self.drain()
        if self.pending is not None:raise RuntimeError('CLEAR cannot interleave a target transaction')
        reason=self.pending_clear
        self.pending_clear=None
        self.clear_ack=False
        self.last_clear_at=time.monotonic()
        self.last_tx_started=self.last_clear_at
        self.consecutive_clears+=1
        self.link._write_line('clear')
        self.counts['clear_sent']+=1
        self.record(tx='clear',robot_state_change=True,reason=reason)
        end=time.monotonic()+self.c['serial']['io_timeout_s']
        while not self.stopping and time.monotonic()<end:
            self.receive(max(0,end-time.monotonic()))
            if self.clear_ack:
                self.drain()
                self.force_fresh_target=True  # Reacquire HTTP, never retry a cached target.
                return
        if not self.stopping:raise TimeoutError('no master OK CLEAR before deadline')

    def query_cfg(self):
        self.drain()
        self.link.send_query('cfg')
        self.record(tx='cfg',motion_tx=False)
        end=time.monotonic()+self.c['serial']['io_timeout_s']
        while not self.stopping and time.monotonic()<end:
            self.receive(max(0,end-time.monotonic()))
            if set(self.ref.expected_nodes)<=self.ref.cfg.keys():
                self.drain()
                break
        self.drain()
        if not set(self.ref.expected_nodes)<=self.ref.cfg.keys():raise ValueError('missing live CFG')
        self.last_cfg_at=time.monotonic()

    def exchange(self,polar,motion,duration_ms=None):
        self.drain()
        if self.node_gate:self.ref.targets(tuple(float(f'{v:.3f}') for v in polar))
        self.pending=polar
        self.pending_match=None
        self.pending_rejected=None
        self.pending_move_rejected=False
        if motion:
            duration=self.map.duration_ms if duration_ms is None else duration_ms
            self.last_tx_started=time.monotonic()
            self.link.send_look(polar,duration)
            self.counts['look']+=1
            cmd=f'look {polar[0]:.3f} {polar[1]:.3f} {polar[2]:.3f} {duration}'
        else:
            self.link.send_ik(*polar)
            cmd=f'ik {polar[0]:.3f} {polar[1]:.3f} {polar[2]:.3f}'
        self.record(tx=cmd,motion_tx=motion)
        end=time.monotonic()+self.c['serial']['io_timeout_s']
        while time.monotonic()<end:
            self.receive(max(0,end-time.monotonic()))
            if self.pending_rejected is not None:
                self.record(master_command_rejected=self.pending_rejected,motion_tx=False)
                self.counts['master_command_rejections']+=1
                self.pending=self.pending_match=None
                self.pending_rejected=None
                self.drain()
                return False
            if self.pending_match is not None:
                self.drain()
                self.record(echo=self.pending_match,motion_tx=False)
                self.pending=self.pending_match=None
                self.counts['echo' if motion else 'ik']+=1
                if motion and not self.pending_move_rejected and self.pending_clear is None:
                    self.consecutive_clears=0
                return True
        raise TimeoutError('no verified master echo')

    def step(self):
        now=time.monotonic()
        self.service_clear()
        if self.node_gate and now-self.last_status_at>=self.c['status_period_s']:
            self.query_status()
        if now-self.last_cfg_at>=self.c['cfg_period_s']:
            verify_files(self.c)
            self.query_cfg()
        if self.stopping:return
        if self.node_gate and not self.robot.ready(time.monotonic(),self.c['status_max_age_s']):
            if self.ever_armed:raise ValueError('robot lost fresh readiness')
            self.publish('WAIT_ROBOT',source='NONE',reason='no motion until online/homed/error-free')
            return
        if self.first_target_at is not None:
            elapsed=time.monotonic()-self.first_target_at
            if self.node_gate and elapsed>self.c['first_timeout_s']:
                raise TimeoutError('first-target movement did not report IDLE before timeout')
            if (elapsed<self.c['first_duration_ms']/1000 or
                    (self.node_gate and (any(n['state']!='IDLE' for n in self.robot.nodes.values()) or
                     self.robot.complete_at is None or self.robot.complete_at<self.first_target_at+self.c['first_duration_ms']/1000))):
                self.publish('FIRST_TARGET_MOVING',reason='slow first live target; no queued camera frames')
                return
            self.first_target_at=None
        if self.node_gate and not self.ever_armed and any(n['state']!='IDLE' for n in self.robot.nodes.values()):
            self.publish('WAIT_ROBOT',source='NONE',reason='first live target waits for robot IDLE')
            return
        if self.emit and self.last_tx_started is not None and time.monotonic()-self.last_tx_started<1/self.c['poll_hz']:
            # Wait for the next allowed TX slot, not an entire extra poll period.
            # Acquire HTTP AFTER waiting so the target is still the newest frame.
            allowed=self.last_tx_started+1/self.c['poll_hz']
            while not self.stopping and time.monotonic()<allowed:
                self.receive(min(.01,max(0,allowed-time.monotonic())))
            if self.stopping:return
        self.drain()
        request_at=time.monotonic()
        try:
            with urllib.request.urlopen(self.c['status_url'],timeout=self.c['serial']['io_timeout_s']) as r:
                s=json.load(r)
        except (OSError,ValueError) as exc:
            self.selector.reset()
            self.publish('WAIT_CAPTURE',source='NONE',reason=str(exc))
            return
        received_at=time.monotonic()
        decision=self.selector.select(s,received_at,received_at-request_at)
        self.record(frame_sequence=s.get('frame_sequence'),decision=decision.__dict__,
                    output_left=s.get('output_left'),output_right=s.get('output_right'),
                    head_sign_validated=s.get('fallback',{}).get('config',{}).get('head_sign_validated'))
        if decision.xy is None:
            self.publish('WAIT_SOURCE',source='NONE',reason=decision.reason)
            return
        desired_polar=scaled_polar(self.map,decision.xy,self.c['tilt_multiplier'],self.c['output_tilt_cap_deg'])
        # Compare after gain/cap, to last actual wire orientation, not last frame.
        delta=None if self.last_polar is None else direction_delta_deg(desired_polar,self.last_polar)
        if self.ever_armed and not self.force_fresh_target and delta is not None and delta < self.c['deadband_deg']:
            self.counts['deadband_skips']+=1
            self.publish('HOLD_DEADBAND',source=decision.source,reason='scaled direction change below angular deadband',
                         desired_xy=decision.xy,command_xy=self.last_xy,desired_polar=desired_polar,
                         direction_delta_deg=delta,frame_sequence=s['frame_sequence'])
            return
        elapsed=1/self.c['poll_hz'] if self.last_sent_at is None else min(
            time.monotonic()-self.last_sent_at,1/self.c['poll_hz'])
        xy=decision.xy if not self.ever_armed else slew_xy(self.last_xy,decision.xy,elapsed,self.c['slew_per_s'])
        polar=scaled_polar(self.map,xy,self.c['tilt_multiplier'],self.c['output_tilt_cap_deg'])
        wire=tuple(float(f'{v:.3f}') for v in polar)
        if self.last_polar is not None and not self.force_fresh_target and direction_delta_deg(wire,self.last_polar)<self.c['deadband_deg']:
            self.counts['deadband_skips']+=1
            self.publish('HOLD_DEADBAND',source=decision.source,reason='slewed wire direction still below angular deadband')
            return
        try:
            motors=self.ref.targets(wire)
        except ValueError as exc:
            if self.node_gate:raise
            # At the requested larger angle, valid finite targets can exceed
            # inspected node travel. Still test the real master's parser; it
            # must reject them. Do not fabricate replies or alter travel limits.
            self.record(local_ik_rejection=str(exc),wire_polar=wire,submitted_to_master_for_test=True)
            motors=None
        bound=self.c['first_motor_step_deg'] if not self.ever_armed else self.c['max_motor_step_deg']
        try:
            if self.node_gate:
                motion_gate(self.robot,time.monotonic(),self.c['status_max_age_s'],motors,self.ref.cfg,bound)
        except ValueError as exc:
            if self.ever_armed and self.emit and 'target jump' in str(exc):
                self.last_status_at=0
                self.publish('WAIT_POSITION',source=decision.source,reason=str(exc))
                return
            if self.emit or 'target jump' not in str(exc):
                raise
        # Conservative include HTTP duration and all local processing in freshness.
        frame_age=s.get('last_frame_age_seconds')
        if not finite_number(frame_age) or frame_age+time.monotonic()-request_at>self.c['frame_max_age_s']:
            self.publish('WAIT_SOURCE',source='NONE',reason='frame expired before TX')
            return
        first=not self.ever_armed
        sent_at=time.monotonic()
        echoed=self.exchange(polar,self.emit,self.c['first_duration_ms'] if first else None)
        if first and self.emit:
            self.first_target_at=sent_at
        self.ever_armed=True
        self.last_xy=xy
        self.last_polar=wire
        self.force_fresh_target=False
        self.last_sent_at=time.monotonic()
        self.counts['source_'+decision.source]+=1
        self.publish(('SENDING_TEST' if not self.node_gate else 'TRACKING') if self.emit else 'IK_ONLY',
                     source=decision.source,reason=decision.reason,last_command_echo_verified=echoed,
                     desired_xy=decision.xy,command_xy=xy,polar=wire,frame_sequence=s['frame_sequence'],
                     head_sign_validated=s['fallback']['config'].get('head_sign_validated'))

    def run(self,max_seconds=None):
        start=time.monotonic()
        try:
            verify_files(self.c)
            if self.latch.exists():
                self.publish('FAULT_LATCHED',source='NONE',reason='persistent fault latch; manual review required')
            else:
                while not self.stopping and not unique_usb_device(self.c):
                    self.publish('WAIT_USB',reason='waiting for unique configured USB adapter')
                    if max_seconds is not None and time.monotonic()-start>=max_seconds:return
                    time.sleep(.5)
                if self.stopping:return
                self.link=TrialSerial(SerialPolicy(**self.c['serial']))
                self.link.open()
                self.record(opened=True,device=self.c['serial']['device'],emit=self.emit)
                end=time.monotonic()+self.c['startup_listen_s']
                while not self.stopping and time.monotonic()<end:
                    self.receive(max(0,end-time.monotonic()))
                if not self.node_gate:self.discard_startup_diagnostic()
                if self.node_gate:self.query_status()
                self.query_cfg()
                # No movement: verify current six-motor semantics at startup.
                self.exchange((0,0,0),False)
                if self.node_gate:self.query_status()
                next_tick=time.monotonic()
                while not self.stopping and (max_seconds is None or time.monotonic()-start<max_seconds):
                    prior_tx=self.last_tx_started
                    self.step()
                    next_tick=max((self.last_tx_started+1/self.c['poll_hz']) if self.last_tx_started!=prior_tx
                                  else time.monotonic()+1/self.c['poll_hz'],time.monotonic())
                    while not self.stopping and time.monotonic()<next_tick:
                        self.receive(min(.05,max(0,next_tick-time.monotonic())))
        except (OSError,ValueError,RuntimeError) as exc:
            self.fault(exc)
        finally:
            if self.link is not None:self.link.close()
        # Keep a visible latched process; systemd must not reopen/replay forever.
        while not self.stopping and self.latch.exists() and max_seconds is None:
            time.sleep(.5)
        if not self.latch.exists():self.publish('STOPPED',source='NONE',reason='worker stopped; no new command or neutral sent')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,required=True)
    p.add_argument('--emit-owner-approved',action='store_true')
    p.add_argument('--seconds',type=float)
    a=p.parse_args()
    if a.seconds is not None and (not finite_number(a.seconds) or a.seconds<=0):p.error('positive validation duration required')
    w=Worker(load_config(a.config),a.emit_owner_approved)
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:setattr(w,'stopping',True))
    w.run(a.seconds)
    return int(w.latch.exists())


if __name__=='__main__':raise SystemExit(main())
