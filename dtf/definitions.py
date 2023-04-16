import datetime
from typing import Optional

import pydantic


class ChannelInfo(pydantic.BaseModel):
    channel_id: str
    channel_title: str
    playlist_id: str
    last_updated_datetime: Optional[datetime.datetime] = None
    videos_sha1hash: str
    videos: list[dict]

    def dict(self, *args, **kwargs) -> dict:
        d = super().dict()
        # update datetime to json compatable value
        if d["last_updated_datetime"] is not None and not isinstance(d["last_updated_datetime"], str):
            d["last_updated_datetime"] = d["last_updated_datetime"].isoformat()
        return d

    @property
    def channel_upload_playlist_id(self):
        playlist_id = "UU" + self.channel_id[2:]
        return playlist_id
