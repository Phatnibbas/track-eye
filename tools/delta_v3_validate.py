"""Generation-3 bounded status/IK + camera probe; NEVER sends motion or settings."""
import argparse
import json
import math
from pathlib import Path
import random
import statistics
import sys
import time
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from delta_bridge.config import SerialPolicy, exact_keys, positive, _read
from delta_bridge.core import Mapping, production_target
from delta_bridge.serial_transport import ReadOnlySerial, SerialProtocolError
from delta_bridge.v3 import V3Reference, V3Snapshot
from tools.delta_protocol_audit import drain_diagnostics


def load_config(path):
    c = _read(path)
    exact_keys(c,('schema_version','serial','expected_eyes','expected_vergence_deg','snapshot_window_s',
                  'startup_listen_s','sync_attempts','queries','rate_hz','seed','tilt_min_deg','tilt_max_deg',
                  'twist_deg','numeric_tolerance_deg','status_every_queries','camera'), 'v3 audit')
    if type(c['schema_version']) is not int or c['schema_version']!=1:
        raise ValueError('unsupported schema')
    exact_keys(c['serial'],('device','baud','io_timeout_s','max_line_bytes'),'serial')
    SerialPolicy(**c['serial'])
    V3Snapshot(c['expected_eyes'],c['expected_vergence_deg'],c['snapshot_window_s'])
    for key in ('startup_listen_s','rate_hz','numeric_tolerance_deg','tilt_max_deg'):
        positive(c[key],key)
    for key in ('sync_attempts','queries','status_every_queries'):
        if type(c[key]) is not int or c[key]<=0:
            raise ValueError('explicit positive count required: '+key)
    if type(c['seed']) is not int or type(c['tilt_min_deg']) not in (int,float) or not math.isfinite(c['tilt_min_deg']) or not 0<=c['tilt_min_deg']<=c['tilt_max_deg']:
        raise ValueError('invalid seed/tilt interval')
    if type(c['twist_deg']) not in (int,float) or not math.isfinite(c['twist_deg']):
        raise ValueError('invalid twist')
    exact_keys(c['camera'],('seconds','poll_hz','status_url','frame_max_age_s','mapping'),'camera')
    for key in ('seconds','poll_hz','frame_max_age_s'):
        positive(c['camera'][key],key)
    if not isinstance(c['camera']['status_url'],str) or not c['camera']['status_url'].startswith('http://127.0.0.1:'):
        raise ValueError('explicit loopback production status URL required')
    exact_keys(c['camera']['mapping'],('slot','max_tilt_deg','az_offset_deg','x_sign','y_sign','twist_deg','duration_ms'),'mapping')
    Mapping(**c['camera']['mapping'])
    return c


def run(c, directory, out_path, summary_path):
    ref = V3Reference(directory,c['expected_eyes'],c['expected_vergence_deg'])
    state = V3Snapshot(c['expected_eyes'],c['expected_vergence_deg'],c['snapshot_window_s'])
    policy = SerialPolicy(**c['serial'])
    link = ReadOnlySerial(policy)
    start = time.monotonic()
    synthetic = camera_matches = camera_samples = camera_skips = 0
    latencies = []
    max_error = 0.0
    diagnostic = []
    failure = None
    statuses = []
    waiting_ik = False
    with out_path.open('x',encoding='utf-8') as out:
        def log(**data):
            out.write(json.dumps({'t_s':time.monotonic()-start,**data},ensure_ascii=False,allow_nan=False)+'\n')
            out.flush()

        def observe(raw, lines):
            if raw:
                log(rx_hex=raw.hex(),lines=lines)
            for line in lines:
                if 'IK az=' in line and not waiting_ik:
                    raise SerialProtocolError('unsolicited/stale IK outside query')
                if line.startswith('CFG '):
                    ref.apply_cfg(line)
                if line.startswith(('STAT','FAULT','ERR','WARN STOP')) or (line.startswith('EVT') and 'BOOT' in line):
                    state.consume(line,time.monotonic())
                if line.startswith(('ERR','WARN','FAULT','EVT')):
                    diagnostic.append(line)

        def receive(seconds):
            raw, lines = link.receive(seconds)
            observe(raw,lines)
            if link.quarantined:
                raise SerialProtocolError('boot/REPL/traceback; session quarantined')
            return lines

        def drain():
            drain_diagnostics(link,policy.io_timeout_s,observe)

        def status():
            drain()
            state.reset()
            link.send_query('status')
            log(tx='status',motion_tx=False)
            end = time.monotonic()+policy.io_timeout_s
            while time.monotonic()<end:
                receive(max(0,end-time.monotonic()))
                if state.complete_at is not None:
                    drain()
                    evidence=dict(ready=state.ready(time.monotonic(),policy.io_timeout_s),fault=state.fault,
                                  nodes=state.nodes,eyes=c['expected_eyes'],vergence=c['expected_vergence_deg'])
                    statuses.append(evidence)
                    log(snapshot=evidence,motion_tx=False)
                    return
            raise TimeoutError('no complete generation-3 status snapshot')

        def ik(polar, phase, sample):
            nonlocal max_error, waiting_ik
            drain()
            # Evaluate current limits BEFORE transmitting any calculation query.
            wire=tuple(float(f'{v:.3f}') for v in polar)
            ref.targets(wire)
            sent=time.monotonic()
            waiting_ik=True
            link.send_ik(*polar)
            log(tx=f'ik {polar[0]:.3f} {polar[1]:.3f} {polar[2]:.3f}',phase=phase,sample_id=sample,motion_tx=False)
            match=None
            end=sent+policy.io_timeout_s
            while time.monotonic()<end:
                for line in receive(max(0,end-time.monotonic())):
                    if line.startswith(('ERR ik','ERR sai tham số','ERR lệnh không rõ')):
                        raise SerialProtocolError('master rejected calculation: '+line)
                    if 'IK az=' in line:
                        if not line.startswith('IK ') or match is not None:
                            raise SerialProtocolError('merged/duplicate IK reply')
                        match=ref.compare(polar,line,c['numeric_tolerance_deg'])
                if match is not None:
                    latency=(time.monotonic()-sent)*1000
                    latencies.append(latency)
                    max_error=max(max_error,max(match['errors_deg'].values()))
                    log(phase=phase,sample_id=sample,latency_ms=latency,**match,motion_tx=False)
                    waiting_ik=False
                    return
            raise TimeoutError('no verified IK before deadline')

        try:
            link.open()
            log(opened=True,device=policy.device,baud=policy.baud,motion_tx=False)
            end=time.monotonic()+c['startup_listen_s']
            while time.monotonic()<end:
                receive(max(0,end-time.monotonic()))
            # Drain rejects stale IK instead of assigning it to a new command.
            drain()
            for attempt in range(c['sync_attempts']):
                try:
                    status()
                    break
                except TimeoutError:
                    if attempt+1==c['sync_attempts']:
                        raise
            link.send_query('cfg')
            log(tx='cfg',motion_tx=False)
            end=time.monotonic()+policy.io_timeout_s
            while time.monotonic()<end:
                receive(max(0,end-time.monotonic()))
            drain()
            if not set(ref.expected_nodes)<=ref.cfg.keys():
                raise ValueError('missing live CFG; no IK TX')
            rng=random.Random(c['seed'])
            axes=(0,90,180,270,360)
            next_tx=time.monotonic()
            for sample in range(c['queries']):
                time.sleep(max(0,next_tx-time.monotonic()))
                az=axes[sample] if sample<len(axes) else rng.uniform(0,360)
                tilt=c['tilt_max_deg'] if sample<len(axes) else rng.uniform(c['tilt_min_deg'],c['tilt_max_deg'])
                ik((az,tilt,c['twist_deg']),'synthetic',sample)
                synthetic+=1
                if synthetic%c['status_every_queries']==0:
                    status()
                next_tx=max(next_tx+1/c['rate_hz'],time.monotonic())
            status()
            camera=c['camera']
            mapping=Mapping(**camera['mapping'])
            end=time.monotonic()+camera['seconds']
            previous=None
            next_tx=time.monotonic()
            while time.monotonic()<end:
                with urllib.request.urlopen(camera['status_url'],timeout=policy.io_timeout_s) as response:
                    s=json.load(response)
                camera_samples+=1
                seq=s.get('frame_sequence')
                target=production_target(s,mapping,camera['frame_max_age_s'])
                fresh=type(seq) is int and seq>0 and (previous is None or seq>previous)
                if fresh:
                    previous=seq
                log(camera_status={k:s.get(k) for k in ('frame_sequence','last_frame_age_seconds','face_detected',
                                                      'healthy','capture_alive','output_left','output_right','output_tuning')})
                if target is None or not fresh:
                    camera_skips+=1
                    log(camera_skip='no fresh usable production eye',motion_tx=False)
                else:
                    ik(mapping.polar(*target),'camera',seq)
                    camera_matches+=1
                next_tx=max(next_tx+1/camera['poll_hz'],time.monotonic())
                time.sleep(max(0,next_tx-time.monotonic()))
            status()
        except (OSError,ValueError,RuntimeError) as exc:
            failure=str(exc)
            log(error=failure,last_rx_hex=link.last_rx.hex(),motion_tx=False)
        finally:
            link.close()
            log(closed=True,motion_tx=False)
    ordered=sorted(latencies)
    summary=dict(duration_s=time.monotonic()-start,synthetic_verified=synthetic,
                 synthetic_planned=c['queries'],camera_samples=camera_samples,camera_verified=camera_matches,
                 camera_skipped=camera_skips,error=failure,max_reference_error_deg=max_error if ordered else None,
                 latency_ms=dict(median=statistics.median(ordered),p95=ordered[math.ceil(.95*len(ordered))-1],max=ordered[-1]) if ordered else None,
                 snapshots=statuses,diagnostics=diagnostic,motion_tx=False,
                 limitation='Calculation/echo only; no USB request ID, node ACK or physical accuracy evidence; RAM recovery policy applies')
    with summary_path.open('x',encoding='utf-8') as stream:
        json.dump(summary,stream,indent=2,ensure_ascii=False,allow_nan=False)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,required=True)
    p.add_argument('--reference-dir',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--summary',type=Path,required=True)
    a=p.parse_args()
    result=run(load_config(a.config),a.reference_dir,a.out,a.summary)
    print(json.dumps(result,ensure_ascii=False))
    return int(result['error'] is not None)


if __name__=='__main__':
    raise SystemExit(main())
