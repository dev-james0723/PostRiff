"""Metadata-only proof from an authenticated Twilio packet stream.

One non-silent inbound frame plus a successfully sent non-silent outbound frame
and an uncleared provider mark ACK prove limited packet playback, not that the
whole briefing played, the speaker is James, or any task resumed. No audio kept.
"""
import asyncio
import base64
import binascii
import re
import uuid

from ..agent_team_decision import _question_call,digest,record_verified_bidirectional_media
from .code_speech import PCM


def non_silent_frames(payload):
    if not isinstance(payload,str) or not 1<=len(payload)<=65536:return 0
    try:raw=base64.b64decode(payload,validate=True)
    except (ValueError,binascii.Error):return 0
    if not 160<=len(raw)<=48000:return 0
    # PCMU 8 kHz, 20 ms frames. Discard bytes immediately after this bounded scan.
    return sum(sum(PCM[value]**2 for value in raw[start:start+160])>160*400**2
               for start in range(0,len(raw)-159,160))


class TeamMediaEvidence:
    def __init__(self,service,call,stream_id,question_hash):
        self.service=service
        self.call={key:call[key] for key in ('id','user_id','workspace_id','provider','provider_call_ref','direction','destination_ref','reason_key')}
        self.stream_id=stream_id;self.question_hash=question_hash
        self.input_frames=0;self.pending_mark=None;self.marked_output_frames=0
        self.played_output_frames=0;self.playback_ack_hash=None
        self.attempted=False;self.state='pending'

    @classmethod
    def create(cls,service,call,stream_id):
        """Called only after ASGI signature/account/call/format/claim checks."""
        provider=getattr(service,'provider',None)
        if not provider or provider.name!='twilio' or provider.real is not True or call.get('provider')!='twilio':return None
        if not isinstance(stream_id,str) or not re.fullmatch(r'MZ[0-9a-fA-F]{32}',stream_id):return None
        try:
            cfg=service.hosted.james_daily_call.cfg
            if call.get('user_id')!=cfg.user_id or call.get('workspace_id')!=cfg.workspace_id:return None
            with service.hosted.connection_factory() as db,db.cursor() as cur:
                question=_question_call(cur,call)
                if not question:return None
                cur.execute("SELECT EXISTS(SELECT 1 FROM public.pr_agent_team_call_evidence WHERE call_id=%s AND evidence_kind='media')",(call['id'],))
                row=cur.fetchone()
                if not row or row[0] is not False:return None
            return cls(service,call,stream_id,question['questionSha256'])
        except Exception:return None

    async def inbound(self,payload):
        if self.attempted:return
        self.input_frames=min(1_000_000,self.input_frames+non_silent_frames(payload))
        await self._persist_if_ready()

    def outbound_sent(self,payload):
        if self.attempted or self.pending_mark or self.playback_ack_hash:return None
        frames=non_silent_frames(payload)
        if not frames:return None
        self.marked_output_frames=frames
        self.pending_mark='team-proof-'+uuid.uuid4().hex
        return self.pending_mark

    async def mark_ack(self,name):
        if not self.pending_mark or name!=self.pending_mark or self.attempted:return
        self.played_output_frames=self.marked_output_frames
        self.playback_ack_hash=digest(['twilio-mark:v1',self.call['id'],self.stream_id,self.pending_mark,self.marked_output_frames])
        self.pending_mark=None
        await self._persist_if_ready()

    def cleared(self):
        # Twilio returns marks when clear empties its buffer too. Fence these ACKs.
        self.pending_mark=None;self.marked_output_frames=0

    async def _persist_if_ready(self):
        if self.attempted or not self.input_frames or not self.played_output_frames or not self.playback_ack_hash:return
        # Set before I/O: unknown commit outcomes never cause another insert attempt.
        self.attempted=True
        evidence=digest(['authenticated-packets:v1',self.call['id'],self.question_hash,self.stream_id,
                         self.input_frames,self.played_output_frames,self.playback_ack_hash])
        try:
            def persist():
                with self.service.hosted.connection_factory() as db,db.cursor() as cur:
                    recorded=record_verified_bidirectional_media(cur,self.call,call_ref=self.call['provider_call_ref'],
                        input_frames=self.input_frames,output_frames=self.played_output_frames,
                        observed_at=self.service.clock(),evidence_sha256=evidence,playback_ack_sha256=self.playback_ack_hash)
                    if recorded:db.commit()
                    return recorded
            self.state='persisted' if await asyncio.to_thread(persist) else 'blocked'
        except Exception:self.state='unknown'
