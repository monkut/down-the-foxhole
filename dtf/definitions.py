import pydantic


class ChannelInfo(pydantic.BaseModel):
    channel_id: str
    channel_title: str
    playlist_id: str
    videos_sha1hash: str
    videos: list[dict]

    @property
    def channel_upload_playlist_id(self):
        playlist_id = "UU" + self.channel_id[2:]
        return playlist_id
