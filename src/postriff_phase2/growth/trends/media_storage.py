"""Deadline-isolated calls to the existing private SupabaseStorage boundary.

The fresh child receives its credential only on stdin, performs exactly one
bounded HEAD/range operation, and emits content-free failures. No URLs or
credentials enter durable media controls. No external provider/model client.
"""
import base64
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time

from . import contracts
from ...hosted_storage import SupabaseStorage

MAX_BYTES = 8 * 1024 * 1024
MAX_REQUEST = 32768
MAX_RESPONSE = ((MAX_BYTES + 2) // 3) * 4 + 2048


def _fail(code):
    raise contracts.ContractError('media_storage_' + code)


def remaining(deadline):
    if type(deadline) not in (int, float) or not math.isfinite(deadline): _fail('deadline_required')
    left = deadline - time.monotonic()
    if left <= 0: _fail('deadline')
    return left


def _request(value):
    if not isinstance(value, dict) or set(value) != {'configuration','operation','workspace_id','object_name','length'}:
        _fail('request')
    contracts.uuid(value['workspace_id'])
    if not isinstance(value['object_name'],str) or not re.fullmatch(r'[0-9a-f]{32}\.(mp4|mov)',value['object_name']): _fail('object')
    if value['operation'] not in ('head','range'): _fail('operation')
    length=value['length']
    if (value['operation']=='head' and length is not None) or (value['operation']=='range' and (type(length) is not int or not 1<=length<=MAX_BYTES)):
        _fail('byte_bound')
    cfg=value['configuration']
    if not isinstance(cfg,dict) or set(cfg)!={'project_url','secret_key','bucket','video_bucket'}: _fail('configuration')
    if not all(isinstance(v,str) and 0<len(v)<=8192 for v in cfg.values()): _fail('configuration')
    return value


def _head(value):
    if (not isinstance(value,dict) or set(value)!={'bytes','mime','etag'} or type(value['bytes']) is not int
            or not 0<value['bytes']<=MAX_BYTES or not isinstance(value['mime'],str) or len(value['mime'])>128
            or not isinstance(value['etag'],str) or not 0<len(value['etag'])<=1024): _fail('head_response')
    return value


def _dispatch(request, *, adapter_factory=SupabaseStorage):
    """Private test seam; the module entry point always uses real SupabaseStorage."""
    r=_request(request); storage=adapter_factory(**r['configuration'])
    if r['operation']=='head': return {'head':_head(storage.object_info(r['workspace_id'],'video',r['object_name']))}
    result=storage.read_range(r['workspace_id'],'video',r['object_name'],0,r['length'])
    if (not isinstance(result,dict) or not isinstance(result.get('data'),bytes) or len(result['data'])>r['length']
            or type(result.get('ranged')) is not bool): _fail('range_response')
    return {'data':base64.b64encode(result['data']).decode('ascii'),'ranged':result['ranged']}


def _child():
    try:
        raw=sys.stdin.buffer.read(MAX_REQUEST+1)
        if len(raw)>MAX_REQUEST: _fail('request_bound')
        output=json.dumps(_dispatch(json.loads(raw)),separators=(',',':')).encode()
        if len(output)>MAX_RESPONSE: _fail('response_bound')
        sys.stdout.buffer.write(output)
        return 0
    except Exception:
        # Never echo an exception, request, host, object name or credential.
        sys.stdout.buffer.write(b'{"error":"media_storage_failed"}')
        return 1


def _communicate(request, deadline):
    _request(request)
    raw=json.dumps(request,separators=(',',':')).encode()
    if len(raw)>MAX_REQUEST: _fail('request_bound')
    remaining(deadline)
    environment={'PATH':'/usr/bin:/bin','LC_ALL':'C','PYTHONDONTWRITEBYTECODE':'1',
                 'PYTHONPATH':str(Path(__file__).resolve().parents[3])}
    process=subprocess.Popen([sys.executable,'-m',__name__],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL,shell=False,close_fds=True,start_new_session=True,env=environment)
    try:
        try:
            output,_=process.communicate(raw,timeout=remaining(deadline))
        except subprocess.TimeoutExpired:
            process.kill(); process.communicate()
            _fail('deadline')
        remaining(deadline)
        if process.returncode!=0 or len(output)>MAX_RESPONSE: _fail('transport_failed')
        try: result=json.loads(output)
        except (ValueError,UnicodeError): _fail('response')
        if not isinstance(result,dict) or 'error' in result: _fail('transport_failed')
        return result
    finally:
        if process.poll() is None:
            process.kill(); process.communicate()
        # communicate reaps; finally also closes pipes on early validation errors.
        for stream in (process.stdin,process.stdout):
            if stream is not None: stream.close()


class BoundedStorage:
    """One media run: at most two objects, six calls, two8MiB reads."""
    def __init__(self, storage, *, deadline):
        if (type(storage) is not SupabaseStorage or getattr(storage.send,'__self__',None) is not storage
                or getattr(storage.send,'__func__',None) is not SupabaseStorage._send): _fail('unsupported_transport')
        # The child reconstructs the canonical no-redirect adapter, so custom
        # opener/transport objects can never cross this boundary.
        from urllib.request import OpenerDirector
        from ...hosted_storage import storage_opener
        if type(storage.opener) is not OpenerDirector or {type(h) for h in storage.opener.handlers}!={type(h) for h in storage_opener().handlers}:
            _fail('unsupported_transport')
        if remaining(deadline)>180: _fail('deadline_bound')
        self._configuration={k:getattr(storage,k) for k in ('project_url','secret_key','bucket','video_bucket')}
        self.deadline=deadline; self._objects={}; self._calls=0

    def _call(self, operation, workspace_id, category, object_name, length=None):
        if category!='video': _fail('category')
        key=(workspace_id,object_name); phase=self._objects.get(key,0)
        if (self._calls>=6 or (key not in self._objects and len(self._objects)>=2)
                or (operation=='head' and phase not in (0,2)) or (operation=='range' and phase!=1)):
            _fail('call_bound')
        request={'configuration':self._configuration,'operation':operation,'workspace_id':workspace_id,'object_name':object_name,'length':length}
        _request(request); remaining(self.deadline)
        self._calls+=1; self._objects[key]=phase+1
        return _communicate(request,self.deadline)

    def object_info(self, workspace_id, category, object_name):
        value=self._call('head',workspace_id,category,object_name)
        if set(value)!={'head'}: _fail('head_response')
        return _head(value['head'])

    def read_range(self, workspace_id, category, object_name, start, length):
        if type(start) is not int or start!=0: _fail('range_start')
        value=self._call('range',workspace_id,category,object_name,length)
        if set(value)!={'data','ranged'} or type(value['ranged']) is not bool or not isinstance(value['data'],str): _fail('range_response')
        try: data=base64.b64decode(value['data'],validate=True)
        except (ValueError,TypeError): _fail('range_response')
        if len(data)>length: _fail('byte_bound')
        return {'data':data,'ranged':value['ranged']}


if __name__=='__main__':
    raise SystemExit(_child())
