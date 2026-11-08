"""Coordinator state machine. All mutations share one lock and monotonic clock."""
from collections import deque
import copy
import secrets
import threading
import time

from .protocol import NODES, LEASE_S, STALE_S, APPROVAL_S, DELIVERY_S, validate_action


class Conflict(ValueError):
    pass


class Coordinator:
    def __init__(self, clock=time.monotonic):
        self.clock, self.lock = clock, threading.RLock()
        self.instance = secrets.token_hex(16)
        self.owner, self.lease_until = None, 0
        self.paused, self.reason = True, 'Awaiting operator'
        self.revision = 0
        self.nodes = {n: dict(last=None, boot=None, mode=None, telemetry={}, safety=None) for n in NODES}
        self.commands, self.events = deque(maxlen=150), deque(maxlen=100)

    def event(self, message):
        self.events.appendleft(dict(time=time.strftime('%H:%M:%S', time.gmtime()), message=message))

    def halt(self, reason):
        self.paused, self.reason = True, reason
        self.revision += 1
        for cmd in self.commands:
            if cmd['status'] in ('pending', 'approved'):
                cmd['status'] = 'cancelled'
        for node, info in self.nodes.items():
            if node != 'jetson':
                info['safety'] = dict(id=secrets.token_hex(12), action='stop' if node == 'rover' else 'land')
        self.event(reason + '; stop/landing requested (physical outcome unconfirmed)')

    def tick(self):
        now = self.clock()
        if self.owner and now >= self.lease_until:
            self.owner = None
            self.halt('Operator heartbeat lost')
        if not self.paused:
            for name, node in self.nodes.items():
                if node['last'] is not None and now - node['last'] > STALE_S:
                    self.halt(name + ' heartbeat lost')
                    break
        for cmd in self.commands:
            if cmd['status'] in ('pending', 'approved') and now >= cmd['expires']:
                cmd['status'] = 'expired'
            if cmd['status'] == 'dispatched' and now >= cmd['expires'] + 3:
                cmd['status'] = 'unconfirmed'
                self.halt('Action acknowledgement lost')

    def require_owner(self, session):
        self.tick()
        if not self.owner or session != self.owner:
            raise Conflict('Claim operator control first; another operator may own it')

    def operator(self, operation, data):
        with self.lock:
            self.tick()
            if operation == 'claim':
                if self.owner:
                    raise Conflict('Operator control is already held; wait for its lease to expire')
                self.owner, self.lease_until = secrets.token_hex(24), self.clock() + LEASE_S
                self.event('Operator claimed control')
                return dict(session=self.owner)
            # Any authenticated operator can stop, even without the control lease.
            if operation in ('pause', 'stop'):
                self.halt('Operator ' + operation)
                return dict(ok=True)
            self.require_owner(data.get('session'))
            if operation == 'heartbeat':
                self.lease_until = self.clock() + LEASE_S
            elif operation == 'resume':
                for name, node in self.nodes.items():
                    if node['last'] is not None:
                        self.ready(name)
                self.paused, self.reason = False, 'Operator control active'
                self.event('Operator enabled proposals; each action still needs approval')
            elif operation == 'propose':
                if self.paused:
                    raise Conflict('Resume operator control first')
                node, action = data.get('node'), data.get('action')
                params = validate_action(node, action, data.get('params', {}))
                self.ready(node)
                if any(c['node'] == node and c['status'] in ('pending', 'approved', 'dispatched') for c in self.commands):
                    raise Conflict('This device already has a pending action')
                cmd = dict(id=secrets.token_hex(12), node=node, action=action, params=params,
                           status='pending', expires=self.clock() + APPROVAL_S, result='')
                self.commands.appendleft(cmd)
                self.event(f'Approval requested: {node} {action}')
                return dict(id=cmd['id'])
            elif operation in ('approve', 'reject'):
                cmd = next((c for c in self.commands if c['id'] == data.get('id')), None)
                if not cmd or cmd['status'] != 'pending':
                    raise Conflict('Proposal is no longer pending')
                if operation == 'approve':
                    if self.paused:
                        raise Conflict('Mission is paused')
                    self.ready(cmd['node'])
                    cmd.update(status='approved', expires=self.clock() + DELIVERY_S)
                else:
                    cmd['status'] = 'rejected'
                self.event(f'{cmd["node"]} {cmd["action"]}: {cmd["status"]}')
            else:
                raise ValueError('Unknown operator operation')
            return dict(ok=True)

    def ready(self, name):
        node = self.nodes[name]
        if node['last'] is None or self.clock() - node['last'] > STALE_S or node['telemetry'].get('ready') is not True:
            raise Conflict(name + ' is offline or not ready')
        if node['safety']:
            raise Conflict('Wait for the device to receive its stop/landing request')

    def sync(self, name, data):
        with self.lock:
            self.tick()
            node, now = self.nodes[name], self.clock()
            boot, mode, telemetry = data.get('boot'), data.get('mode'), data.get('telemetry')
            if not isinstance(boot, str) or not 8 <= len(boot) <= 100 or mode not in ('LIVE', 'SIMULATED') or not isinstance(telemetry, dict):
                raise ValueError('Invalid node heartbeat')
            if node['boot'] != boot:
                if node['last'] is not None and now - node['last'] <= STALE_S:
                    raise Conflict('Another agent owns this device; stop it before replacing it')
                self.halt(name + ' connected/restarted')
            node.update(last=now, boot=boot, mode=mode, telemetry=copy.deepcopy(telemetry))
            if not self.paused and (telemetry.get('agent_error') or telemetry.get('ready') is not True):
                self.halt(name + ' reported a device/network error or is not ready')
            result = data.get('result')
            if isinstance(result, dict):
                cmd = next((c for c in self.commands if c['id'] == result.get('id') and c['node'] == name), None)
                if cmd and cmd['status'] in ('dispatched', 'unconfirmed'):
                    cmd.update(status='acknowledged' if result.get('ok') is True else 'failed',
                               result=str(result.get('detail', ''))[:300])
                    self.event(f'{name} {cmd["action"]}: {cmd["status"]}')
                    if cmd['status'] == 'failed':
                        self.halt(name + ' rejected an action')
            command = None
            if node['safety']:
                command, node['safety'] = node['safety'], None
                command = dict(command, params={}, safety=True, ttl_s=DELIVERY_S)
            elif not self.paused and self.owner:
                cmd = next((c for c in self.commands if c['node'] == name and c['status'] == 'approved'), None)
                if cmd:
                    cmd['status'] = 'dispatched'
                    command = dict(id=cmd['id'], action=cmd['action'], params=cmd['params'],
                                   ttl_s=max(0, cmd['expires'] - now), safety=False)
            return dict(instance=self.instance, revision=self.revision, paused=self.paused,
                        lease_s=max(0, self.lease_until - now) if self.owner else 0, command=command)

    def snapshot(self):
        with self.lock:
            self.tick()
            now = self.clock()
            nodes = {name: dict(mode=n['mode'], telemetry=copy.deepcopy(n['telemetry']),
                     online=n['last'] is not None and now - n['last'] <= STALE_S,
                     age_s=None if n['last'] is None else round(now - n['last'], 2)) for name, n in self.nodes.items()}
            commands = [dict({k: copy.deepcopy(v) for k, v in c.items() if k != 'expires'},
                             remaining_s=round(max(0, c['expires'] - now), 1)) for c in self.commands]
            return dict(instance=self.instance, paused=self.paused, reason=self.reason,
                        operator_active=bool(self.owner), lease_s=round(max(0, self.lease_until - now), 2),
                        nodes=nodes, commands=commands, events=list(self.events))
