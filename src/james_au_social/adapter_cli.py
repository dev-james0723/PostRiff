"""Channel-pinned JSON handoff CLI; no external operations."""
import argparse
import json
from pathlib import Path
from .channel_adapters import draft_handoff

def run(channel):
    parser=argparse.ArgumentParser(description='Create a local, non-publishing channel handoff')
    parser.add_argument('--input',required=True,type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.input.is_symlink() or args.input.stat().st_size>2_000_000:
        raise ValueError('bounded_regular_input_required')
    draft=json.loads(args.input.read_text())
    if draft.get('channel')!=channel:
        raise ValueError('adapter_channel_mismatch')
    result=draft_handoff(draft)
    encoded=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.output:
        with args.output.open('x',encoding='utf-8') as stream:
            stream.write(encoded)
    else:
        print(encoded,end='')
