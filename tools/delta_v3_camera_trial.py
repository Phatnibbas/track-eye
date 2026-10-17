"""Operator-approved bounded shared-target v3 camera trial. No auto recovery.

Single display slot supplies both active Delta mechanisms. Each command needs a
fresh status + verified IK + limited motor step. This does not certify mechanics.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from delta_bridge.config import SerialPolicy, exact_keys, positive, _read
from delta_bridge.core import Mapping, production_target
from delta_bridge.serial_transport import ReadOnlySerial, SerialProtocolError
from delta_bridge.v3 import V3Reference, V3Snapshot, motion_gate
from tools.delta_protocol_audit import drain_diagnostics


class TrialSerial(ReadOnlySerial):
    def send_look(self, polar, duration_ms):
        from delta_bridge.core import finite_number
        if any(not finite_number(v) for v in polar) or type(duration_ms) is not int or not 1 <= duration_ms <= 65535:
            raise ValueError('finite angles/integer duration required')
        self._write_line(f'look {polar[0]:.3f} {polar[1]:.3f} {polar[2]:.3f} {duration_ms}')


def load_trial(path):
    c=_read(path)
    exact_keys(c,('schema_version','serial','expected_eyes','expected_vergence_deg','mapping','seconds',
                  'poll_hz','status_url','frame_max_age_s','status_max_age_s','snapshot_window_s',
                  'numeric_tolerance_deg','max_motor_step_deg','expected_calibration_sha256'), 'v3 trial')
    if type(c['schema_version']) is not int or c['schema_version'] != 1:
        raise ValueError('unsupported trial schema')
    exact_keys(c['serial'],('device','baud','io_timeout_s','max_line_bytes'),'serial')
    SerialPolicy(**c['serial'])
    V3Snapshot(c['expected_eyes'],c['expected_vergence_deg'],c['snapshot_window_s'])
    exact_keys(c['mapping'],('slot','max_tilt_deg','az_offset_deg','x_sign','y_sign','twist_deg','duration_ms'),'mapping')
    Mapping(**c['mapping'])
    for key in ('seconds','poll_hz','frame_max_age_s','status_max_age_s','numeric_tolerance_deg','max_motor_step_deg'):
        positive(c[key],key)
    if c['poll_hz'] > 15:
        raise ValueError('trial rate exceeds inspected firmware MOVE cap')
    if not isinstance(c['status_url'],str) or not c['status_url'].startswith('http://127.0.0.1:'):
        raise ValueError('explicit loopback production status URL required')
    h=c['expected_calibration_sha256']
    if not isinstance(h,str) or len(h)!=64 or any(ch not in '0123456789abcdef' for ch in h):
        raise ValueError('explicit current Pi calibration hash required')
    return c


def load_approach(path):
    c=_read(path)
    exact_keys(c,('duration_ms','timeout_s','position_tolerance_deg','max_motor_step_deg',
                  'status_poll_hz','stable_snapshots'),'neutral approach')
    if type(c['duration_ms']) is not int or not 1 <= c['duration_ms'] <= 65535:
        raise ValueError('explicit neutral duration required')
    for key in ('timeout_s','position_tolerance_deg','max_motor_step_deg','status_poll_hz'):
        positive(c[key],key)
    if c['timeout_s'] <= c['duration_ms']/1000:
        raise ValueError('approach timeout must exceed requested duration')
    if type(c['stable_snapshots']) is not int or c['stable_snapshots'] < 2:
        raise ValueError('at least two post-duration snapshots required')
    return c


def neutral_reported(state, now, max_age_s, targets, tolerance):
    return (state.ready(now,max_age_s) and set(targets)==set(state.nodes)
            and all(node['state']=='IDLE' and abs(node['pos']-targets[n]) <= tolerance
                    for n,node in state.nodes.items()))


def run(c, reference_dir, calibration_path, out_path, summary_path, approach=None):
    link=TrialSerial(SerialPolicy(**c['serial']))
    reference=V3Reference(reference_dir,c['expected_eyes'],c['expected_vergence_deg'])
    state=V3Snapshot(c['expected_eyes'],c['expected_vergence_deg'],c['snapshot_window_s'])
    mapping=Mapping(**c['mapping'])
    start=time.monotonic()
    commands=skipped=verified=0
    neutral_sent=neutral_echo=0
    neutral_complete=False
    failed=None
    expected=None
    pending_match=None
    diagnostics=[]
    with out_path.open('x',encoding='utf-8') as out:
        def log(**data):
            out.write(json.dumps({'t_s':time.monotonic()-start,**data},ensure_ascii=False,allow_nan=False)+'\n')
            out.flush()

        def observe(raw,lines):
            nonlocal pending_match
            if raw:
                log(rx_hex=raw.hex(),lines=lines)
            for line in lines:
                if 'IK az=' in line and expected is None:
                    raise SerialProtocolError('unsolicited IK; motion disarmed')
                if line.startswith('CFG '): reference.apply_cfg(line)
                state.consume(line,time.monotonic())
                if line.startswith(('FAULT','ERR','WARN STOP')) or (line.startswith('EVT') and 'BOOT' in line):
                    diagnostics.append(line)
                    raise SerialProtocolError('motion disarmed: '+line)
                if 'IK az=' in line and not line.startswith('IK '):
                    raise SerialProtocolError('merged IK line')
                if line.startswith('IK '):
                    if pending_match is not None:
                        raise SerialProtocolError('duplicate IK reply')
                    pending_match=reference.compare(expected,line,c['numeric_tolerance_deg'])

        def receive(timeout):
            raw,lines=link.receive(timeout)
            observe(raw,lines)
            if link.quarantined:
                raise SerialProtocolError('boot/REPL/traceback; motion disarmed')
            return lines

        def drain():
            drain_diagnostics(link,c['serial']['io_timeout_s'],observe)

        def status():
            drain()
            state.reset()
            link.send_query('status')
            log(tx='status',motion_tx=False)
            end=time.monotonic()+c['serial']['io_timeout_s']
            while time.monotonic()<end:
                receive(max(0,end-time.monotonic()))
                if state.complete_at is not None:
                    drain()
                    log(snapshot=state.nodes,ready=state.ready(time.monotonic(),c['status_max_age_s']),motion_tx=False)
                    return
            raise TimeoutError('no fresh complete status')

        def echo(polar):
            nonlocal expected,pending_match
            end=time.monotonic()+c['serial']['io_timeout_s']
            while time.monotonic()<end:
                receive(max(0,end-time.monotonic()))
                if pending_match is not None:
                    # A response chunk may contain IK plus a diagnostic fragment.
                    # Drain while tracking the outstanding command so a duplicate
                    # or partial second reply cannot be silently discarded.
                    drain()
                    match=pending_match
                    expected=None
                    pending_match=None
                    log(**match,motion_tx=False)
                    return match
            raise TimeoutError('no verified master echo')

        def camera():
            if hashlib.sha256(Path(calibration_path).read_bytes()).hexdigest() != c['expected_calibration_sha256']:
                raise ValueError('Pi calibration changed; trial disarmed')
            with urllib.request.urlopen(c['status_url'],timeout=c['serial']['io_timeout_s']) as response:
                s=json.load(response)
            log(camera_status={k:s.get(k) for k in ('frame_sequence','healthy','capture_alive',
                                                   'face_detected','last_frame_age_seconds',
                                                   'output_left','output_right','baseline')},motion_tx=False)
            return s,production_target(s,mapping,c['frame_max_age_s'])

        try:
            if hashlib.sha256(Path(calibration_path).read_bytes()).hexdigest() != c['expected_calibration_sha256']:
                raise ValueError('Pi calibration changed; trial disarmed')
            link.open()
            log(opened=True,shared_target_slot=mapping.slot,eyes=c['expected_eyes'],motion_tx=False)
            end=time.monotonic()+c['serial']['io_timeout_s']
            while time.monotonic()<end:
                receive(max(0,end-time.monotonic()))
            status()
            if not state.ready(time.monotonic(),c['status_max_age_s']):
                raise ValueError('initial generation-3 state not ready')
            link.send_query('cfg')
            log(tx='cfg',motion_tx=False)
            end=time.monotonic()+c['serial']['io_timeout_s']
            while time.monotonic()<end:
                receive(max(0,end-time.monotonic()))
            drain()
            # Conservative initial approach gate. Common neutral is already a
            # ~13-degree motor excursion from today's home position. Do not let
            # a 2-degree gaze label hide it; operator must approve approach first.
            status()
            neutral=reference.targets((0,0,0))
            if approach is not None:
                if any(n['state']!='IDLE' for n in state.nodes.values()):
                    raise ValueError('neutral approach requires all active nodes IDLE')
                motion_gate(state,time.monotonic(),c['status_max_age_s'],neutral,
                            reference.cfg,approach['max_motor_step_deg'])
                drain()
                expected=(0,0,0)
                link.send_ik(0,0,0)
                log(tx='ik 0.000 0.000 0.000',phase='neutral',motion_tx=False)
                evidence=echo((0,0,0))
                motion_gate(state,time.monotonic(),c['status_max_age_s'],evidence['reply_motors'],
                            reference.cfg,approach['max_motor_step_deg'])
                expected=(0,0,0)
                sent_at=time.monotonic()
                link.send_look((0,0,0),approach['duration_ms'])
                neutral_sent=1
                log(tx=f"look 0.000 0.000 0.000 {approach['duration_ms']}",phase='neutral',motion_tx=True)
                echo((0,0,0))
                neutral_echo=1
                stable=0
                end_approach=sent_at+approach['timeout_s']
                while time.monotonic()<end_approach:
                    status()
                    if not state.ready(time.monotonic(),c['status_max_age_s']):
                        raise ValueError('robot lost readiness during approved neutral approach')
                    # Do not count optimistic master position before the requested
                    # duration. Query fresh node-reported positions afterwards.
                    reported=(time.monotonic()>=sent_at+approach['duration_ms']/1000
                              and neutral_reported(state,time.monotonic(),c['status_max_age_s'],neutral,
                                                   approach['position_tolerance_deg']))
                    stable=stable+1 if reported else 0
                    log(neutral_reported=reported,stable_snapshots=stable,motion_tx=False)
                    if stable>=approach['stable_snapshots']:
                        neutral_complete=True
                        break
                    time.sleep(1/approach['status_poll_hz'])
                if not neutral_complete:
                    raise TimeoutError('neutral reported completion not verified before deadline; no camera LOOK')
                log(neutral_reported_complete=True,physical_observation_required=True,motion_tx=False)
            motion_gate(state,time.monotonic(),c['status_max_age_s'],reference.targets((0,0,0)),
                        reference.cfg,c['max_motor_step_deg'])
            previous=None
            end=time.monotonic()+c['seconds']
            next_send=time.monotonic()
            while time.monotonic()<end:
                status()
                s,target=camera()
                seq=s.get('frame_sequence')
                if target is None or type(seq) is not int or seq<=0 or (previous is not None and seq<=previous):
                    skipped+=1
                    log(skipped='no fresh usable production eye; no neutral/fallback substitution',sequence=seq,motion_tx=False)
                else:
                    previous=seq
                    polar=mapping.polar(*target)
                    drain()
                    expected=polar
                    link.send_ik(*polar)
                    log(tx=f'ik {polar[0]:.3f} {polar[1]:.3f} {polar[2]:.3f}',sequence=seq,motion_tx=False)
                    evidence=echo(polar)
                    # Re-read latest frame AFTER status/IK. Never reuse cached
                    # camera target if it has aged/restarted/changed meanwhile.
                    fresh,latest=camera()
                    newer=fresh.get('frame_sequence')
                    if latest is None:
                        raise ValueError('camera no longer usable after IK; motion disarmed')
                    if type(newer) is not int or newer<seq:
                        raise ValueError('camera sequence invalid/restarted after IK; motion disarmed')
                    latest_polar=mapping.polar(*latest)
                    latest_wire=tuple(float(f'{v:.3f}') for v in latest_polar)
                    if latest_wire!=tuple(evidence['wire_polar']):
                        log(superseded_ik_sequence=seq,new_sequence=newer,
                            latest_target_used=True,motion_tx=False)
                    # Calculation probe verified the current master's parser/math.
                    # Validate the NEWEST target locally, send it once, then require
                    # its own look echo. Never replay the older checked camera frame.
                    drain()
                    motion_gate(state,time.monotonic(),c['status_max_age_s'],reference.targets(latest_wire),
                                reference.cfg,c['max_motor_step_deg'])
                    expected=latest_polar
                    link.send_look(latest_polar,mapping.duration_ms)
                    commands+=1
                    log(tx=f'look {latest_polar[0]:.3f} {latest_polar[1]:.3f} {latest_polar[2]:.3f} {mapping.duration_ms}',
                        sequence=newer,motion_tx=True)
                    echo(latest_polar)
                    verified+=1
                next_send=max(next_send+1/c['poll_hz'],time.monotonic())
                time.sleep(max(0,next_send-time.monotonic()))
            status()
        except (OSError,ValueError,RuntimeError) as exc:
            failed=str(exc)
            log(error=failed,last_rx_hex=link.last_rx.hex(),motion_tx=False)
        finally:
            link.close()
            log(closed=True,motion_tx=False)
    result=dict(duration_s=time.monotonic()-start,look_sent=commands,look_echo_verified=verified,
                neutral_look_sent=neutral_sent,neutral_echo_verified=neutral_echo,
                neutral_reported_complete=neutral_complete,
                skipped=skipped,error=failed,diagnostics=diagnostics,shared_slot=mapping.slot,
                limitation='No node MOVE ACK, no physical completion claim. Stop sending on loss; firmware has no Pi watchdog.')
    with summary_path.open('x',encoding='utf-8') as out:
        json.dump(result,out,indent=2,ensure_ascii=False)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,required=True)
    p.add_argument('--reference-dir',type=Path,required=True)
    p.add_argument('--calibration-file',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--summary',type=Path,required=True)
    p.add_argument('--operator-approved-shared-look',action='store_true',required=True)
    p.add_argument('--approach-config',type=Path)
    p.add_argument('--operator-approved-neutral-approach',action='store_true')
    a=p.parse_args()
    if bool(a.approach_config)!=a.operator_approved_neutral_approach:
        p.error('neutral approach requires both explicit config and operator approval')
    result=run(load_trial(a.config),a.reference_dir,a.calibration_file,a.out,a.summary,
               load_approach(a.approach_config) if a.approach_config else None)
    print(json.dumps(result,ensure_ascii=False))
    return int(result['error'] is not None or result['look_sent']==0)


if __name__=='__main__':
    raise SystemExit(main())
