# Modified for James Au Studio: exact metadata, no update/comments or credential logging. GPL-3.0, upstream attribution in vendor/recorder.
from __future__ import annotations
import os.path

from bilibili_api.video import video_upload, video_cover_upload, video_submit, get_video_info, video_update

from typing import Any as UploaderAccount


SPECIAL_SPACE = "\u2007"


class UploadTask:

    def __init__(self, session_id, video_path, thumbnail_path, sc_path, he_path, subtitle_path,
                 title, source, description, tag, channel_id, danmaku, account: UploaderAccount):
        self.session_id = session_id
        self.video_path = video_path
        self.sc_path = sc_path
        self.he_path = he_path
        self.subtitle_path = subtitle_path
        self.thumbnail_path = thumbnail_path
        self.title = title
        self.source = source
        self.description = description
        self.tag = tag
        self.channel_id = channel_id
        self.danmaku = danmaku
        self.account = account
        self.verify = self.account.verify
        self.trial = 0

    def upload(self, session_dict: dict[str, str]):
        def on_progress(update):
            pass

        filename = video_upload(self.video_path, verify=self.verify, on_progress=on_progress)
        if self.session_id in session_dict:
            raise ValueError("duplicate_submission")
        if self.session_id not in session_dict:
            cover_url = video_cover_upload(self.thumbnail_path, verify=self.verify)
            data = {
                "copyright": self.copyright,
                "source": self.source,
                "cover": cover_url,
                "desc": self.description,
                "desc_format_id": 0,
                "dynamic": "",
                "interactive": 0,
                "no_reprint": 0,
                "subtitles": {
                    "lan": "",
                    "open": 0
                },
                "tag": self.tag,
                "tid": self.channel_id,
                "title": self.title,
                "videos": [
                    {
                        "desc": "",
                        "filename": filename,
                        "title": self.title
                    }
                ]
            }

            self.before_submit()
            result = video_submit(data, self.verify)

            return result['bvid']
