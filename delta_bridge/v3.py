"""Generation-3 text contract; independent of legacy ACK/queue readiness."""
import ast
import importlib.util
import math
from pathlib import Path
import re
from types import SimpleNamespace

from .core import NODE_RE, finite_number
from .ik_validation import NUMBER, parse_ik

HEADER = re.compile(rf'^STAT fault=(True|False) eyes=(1|2|1\+2|2\+1) verg=({NUMBER})$')
CFG = re.compile(r'^CFG n(\d+) (.+)$')


def constants(path, names):
    values = {}
    for item in ast.parse(Path(path).read_text(encoding='utf-8')).body:
        if isinstance(item, ast.Assign):
            for name in item.targets:
                if isinstance(name, ast.Name) and name.id in names:
                    values[name.id] = ast.literal_eval(item.value)
    if set(values) != set(names):
        raise ValueError('reference constants missing')
    return values


class V3Snapshot:
    def __init__(self, eyes, vergence, window_s):
        if not eyes or len(set(eyes)) != len(eyes) or any(type(e) is not int or e not in (1, 2) for e in eyes):
            raise ValueError('explicit unique generation-3 eyes required')
        if not finite_number(vergence) or not finite_number(window_s) or window_s <= 0:
            raise ValueError('explicit finite vergence/window required')
        self.eyes = frozenset(eyes)
        self.expected_nodes = frozenset(n for e in eyes for n in range(3*e-2, 3*e+1))
        self.vergence = vergence
        self.window_s = window_s
        self.reset()

    def reset(self):
        self.header_at = self.complete_at = None
        self.nodes = {}
        self.fault = True

    def consume(self, line, now):
        if not finite_number(now) or now < 0:
            raise ValueError('invalid observation clock')
        if line.startswith('STAT fault='):
            self.reset()
            m = HEADER.fullmatch(line)
            if m is None or frozenset(int(e) for e in m[2].split('+')) != self.eyes or float(m[3]) != self.vergence:
                raise ValueError('unexpected generation-3 active eyes/vergence/header')
            self.fault = m[1] == 'True'
            self.header_at = now
        elif line.startswith('STAT n'):
            m = NODE_RE.fullmatch(line)
            if m is None or self.header_at is None or not 0 <= now-self.header_at <= self.window_s:
                self.reset()
                raise ValueError('invalid/incomplete generation-3 node snapshot')
            nid, online, state, error, homed, sw, pos, target = m.groups()
            nid = int(nid)
            if nid not in self.expected_nodes or nid in self.nodes or not all(finite_number(float(v)) for v in (pos,target)):
                self.reset()
                raise ValueError('unknown/duplicate/nonfinite generation-3 node')
            self.nodes[nid] = dict(online=online=='ON', state=state, error=error,
                                  homed=homed=='1', switch=sw=='1', pos=float(pos), target=float(target))
            if self.nodes.keys() == self.expected_nodes:
                self.complete_at = now
        elif line.startswith(('FAULT', 'ERR', 'WARN STOP')) or (line.startswith('EVT') and 'BOOT' in line):
            self.reset()

    def ready(self, now, max_age_s):
        return (finite_number(now) and finite_number(max_age_s) and max_age_s > 0
                and self.complete_at is not None and 0 <= now-self.complete_at <= max_age_s
                and not self.fault and self.nodes.keys() == self.expected_nodes
                and all(n['online'] and n['homed'] and n['error']=='NONE' and n['state'] in ('IDLE','MOVING')
                        for n in self.nodes.values()))


def parse_cfg(line):
    m = CFG.fullmatch(line)
    if m is None:
        raise ValueError('not a complete generation-3 CFG')
    values = {}
    for token in m[2].split():
        parts = token.split('=')
        if len(parts) != 2 or parts[0] in values:
            raise ValueError('duplicate/malformed CFG field')
        values[parts[0]] = float(parts[1])
    required = {'min','max','homedir','maxhz','accel','homefast','homeslow','led','enc','encdir'}
    if set(values) != required or not all(finite_number(v) for v in values.values()) or not values['min'] < values['max']:
        raise ValueError('incomplete/nonfinite CFG values')
    return int(m[1]), values


class V3Reference:
    """Run inspected actual IK/mapping methods with board-owned neutral snapshot.

    Same-source numerical comparison, not independent physical truth. No hardware
    imports, Master initialization or source modification.
    """
    def __init__(self, directory, eyes, vergence):
        directory = Path(directory)
        cfg = constants(directory/'main.py', ('MOTOR_SIGN','EYE_CFG','RIGHT_AZ','CFG_FALLBACK'))
        proto = constants(directory/'proto3.py', ('EYES','NUM_NODES'))
        if proto != {'EYES':{1:(1,2,3),2:(4,5,6)},'NUM_NODES':6}:
            raise ValueError('unexpected generation-3 eye topology')
        if len(cfg['MOTOR_SIGN']) != 6 or any(s not in (-1,1) for s in cfg['MOTOR_SIGN']):
            raise ValueError('invalid motor signs')
        spec = importlib.util.spec_from_file_location('delta_v3_reference_ik',directory/'spm_ik.py')
        ik = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ik)
        cls = next(n for n in ast.parse((directory/'main.py').read_text(encoding='utf-8')).body
                   if isinstance(n,ast.ClassDef) and n.name=='Master')
        methods = [n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in
                   ('active_eyes','eye_gaze','eye_targets','look_targets')]
        namespace = {**cfg, 'K':ik, 'P':SimpleNamespace(EYES=proto['EYES'],eye_mask=lambda e:7 << (3*(e-1))),
                     **{name:getattr(math,name) for name in ('sqrt','radians','degrees','atan2','cos','sin')}}
        ast_cls = ast.ClassDef(name='ReferenceMaster',bases=[],keywords=[],body=methods,decorator_list=[])
        tree = ast.fix_missing_locations(ast.Module(body=[ast_cls],type_ignores=[]))
        exec(compile(tree,str(directory/'main.py')+':selected-IK-methods','exec'),namespace)
        self.subject = namespace['ReferenceMaster']()
        self.subject.active = sum(7 << (3*(e-1)) for e in eyes)
        self.subject.verg = vergence
        self.subject.th0 = ik.ik(0,0,0)
        self.subject.neutral = {1:None,2:None}
        for line in (directory/'neutral3.txt').read_text().splitlines():
            fields = line.split()
            if len(fields)!=4 or int(fields[0]) not in (1,2) or self.subject.neutral[int(fields[0])] is not None:
                raise ValueError('invalid/duplicate neutral3 snapshot')
            values = [float(v) for v in fields[1:]]
            if not all(finite_number(v) for v in values):
                raise ValueError('nonfinite neutral3')
            self.subject.neutral[int(fields[0])] = values
        if any(self.subject.neutral[e] is None for e in eyes):
            raise ValueError('active eye has no neutral snapshot')
        self.expected_nodes = tuple(n for e in sorted(eyes) for n in proto['EYES'][e])
        self.cfg = {}
        self.subject.nodes = [SimpleNamespace(target=0,c=lambda key: (_ for _ in ()).throw(ValueError('live CFG not loaded')))
                              for _ in range(6)]

    def apply_cfg(self, line):
        nid, cfg = parse_cfg(line)
        if not 1 <= nid <= 6:
            raise ValueError('unknown CFG node')
        if nid in self.cfg and cfg != self.cfg[nid]:
            raise ValueError('live CFG changed during audit')
        self.cfg[nid] = cfg
        self.subject.nodes[nid-1].c = lambda key, values=cfg: values[key]

    def targets(self, polar):
        if not set(self.expected_nodes) <= self.cfg.keys():
            raise ValueError('live node limits not loaded')
        values, reason = self.subject.look_targets(*polar)
        if reason:
            raise ValueError(reason)
        return {n:values[n-1] for n in self.expected_nodes}

    def compare(self, polar, line, tolerance):
        if not finite_number(tolerance) or tolerance <= 0:
            raise ValueError('explicit positive numerical tolerance required')
        echo, motors = parse_ik(line,self.expected_nodes)
        wire = tuple(float(f'{v:.3f}') for v in polar)
        if echo != wire:
            raise ValueError('generation-3 echo mismatch')
        wanted = self.targets(wire)
        errors = {n:abs(motors[n]-wanted[n]) for n in motors}
        if max(errors.values()) > tolerance:
            raise ValueError('generation-3 reference mismatch')
        return dict(wire_polar=wire,reply_motors=motors,reference_motors=wanted,errors_deg=errors)


def motion_gate(state, now, max_age_s, motors, limits, max_step_deg):
    """Gate one shared-target trial; never infer encoder completion from target."""
    if not finite_number(max_step_deg) or max_step_deg <= 0:
        raise ValueError('explicit positive motor step bound required')
    if not state.ready(now,max_age_s):
        raise ValueError('fresh complete generation-3 ready state required')
    if set(motors) != set(state.expected_nodes) or not set(motors) <= limits.keys():
        raise ValueError('complete active motor targets/live limits required')
    for nid, target in motors.items():
        if not finite_number(target) or not limits[nid]['min'] <= target <= limits[nid]['max']:
            raise ValueError(f'n{nid} IK target outside live limits')
        if abs(target-state.nodes[nid]['pos']) > max_step_deg:
            raise ValueError(f'n{nid} target jump exceeds explicit {max_step_deg:g}-degree bound; separate neutral approval needed')
