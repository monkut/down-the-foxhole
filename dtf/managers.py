import json
import logging
import pickle
import shutil
from pathlib import Path
from typing import Generator, Optional

from .apis import YOUTUBE, S3_CLIENT
from .definitions import ChannelInfo
from .functions import get_channel_videos, create_channel_playlist, get_videos_hash


from . import settings

logger = logging.getLogger(__name__)


class Collector:

    def __init__(self, query_string: str = "babymetal reaction", storage_directory: Path = Path("~/.dtf").expanduser()):
        self.query_string = query_string
        self.storage_directory = storage_directory.expanduser().resolve()
        if not self.storage_directory.exists():
            logger.info("cache directory does not exist, creating ...")
            logger.info(self.storage_directory)
            self.storage_directory.mkdir(parents=True, exist_ok=True)
            logger.info("cache directory does not exist, creating ... DONE")
        self.secrets_json_filepath = storage_directory / "secrets.json"
        self._data = {}

    def set_credentials(self, secrets_filepath: Path) -> bool:
        assert secrets_filepath.exists(), f"not found: {secrets_filepath}"
        shutil.copy(secrets_filepath, self.secrets_json_filepath)
        return True

    def get_existing_playlist_data(self, channel_id: str) -> Optional[ChannelInfo]:
        for item in self.storage_directory.glob("*.json"):
            channel_id = item.stem
            channel_data = self._get_channel_data(channel_id)
            if channel_data:
                self._data[channel_data.channel_id] = channel_data
        return self._data.get(channel_id, None)

    def _get_channel_data(self, channel_id: str) -> Optional[ChannelInfo]:
        channel_filepath = self.storage_directory / channel_id
        channel_data = None
        if channel_filepath.exists():
            # load data
            logger.info(f"reading {channel_filepath}")
            channel_data = ChannelInfo(**json.loads(channel_filepath.read_text()))
        else:
            logger.warning(f"{channel_filepath} does not exist!")
        return channel_data

    def _set_channel_data(self, data: ChannelInfo):
        channel_filepath = self.storage_directory / data.channel_id
        with channel_filepath.open("w", encoding="utf8") as out_f:
            out_f.write(json.dumps(data.dict()))
        self._data[data.channel_id] = data

    def load_previous(self, local_directory: Path = Path("/tmp")):
        local_filepath = local_directory / "previous.pkl"
        with local_filepath.open("wb") as f:
            S3_CLIENT.download_fileobj(settings.S3_BUCKET, settings.PREVIOUS_S3_KEY, f)

        with local_filepath.open("rb") as read_f:
            self._data = pickle.load(read_f)

    def search_for_reactors(self) -> Generator:
        logger.info(f"query_string='{self.query_string}'")
        request = YOUTUBE.search().list(
            part='snippet',
            # 検索したい文字列を指定
            q=self.query_string,
            order='viewCount',
            type='video',
            maxResults=50,
        )
        response = request.execute()
        yield response
        while "nextPageToken" in response and response["nextPageToken"]:
            next_page_token = response["nextPageToken"]
            request = YOUTUBE.search().list(
                part='snippet',
                # 検索したい文字列を指定
                q=self.query_string,
                order='viewCount',
                type='video',
                pageToken=next_page_token,
                maxResults=50,
            )
            response = request.execute()
            yield response

    def update(self, data: dict):
        logger.info(f"")
        for item in data["items"]:
            key = item["channelId"]
            self._data[key].add(item)

    def discover(self) -> list[tuple[str, str]]:
        results = []
        responses = self.search_for_reactors()
        found = False
        for response in responses:
            for item in response["items"]:
                # get channel_id and retrieve all target videos
                channel_id = item["snippet"]["channelId"]
                channel_title = item["snippet"]["channelTitle"]
                if channel_id not in settings.IGNORE_CHANNEL_IDS:
                    channel_info = (channel_id, channel_title)
                    if channel_info not in results:
                        results.append(channel_info)
        return results

    def process_channel(self, channel_id: str):
        channel_data = self.get_existing_playlist_data(channel_id)
        if channel_id in settings.IGNORE_CHANNEL_IDS:
            logger.info(f"skipping channel in ignore list: {channel_id}")
        elif channel_data:
            logger.info(f"playlist already created for: {channel_id}")
            logger.info(f" - cache stored in {self.storage_directory}")
        else:
            logger.info(f"retrieving uploaded videos for {channel_id} ...")
            channel_title, channel_playlist_id, videos = get_channel_videos(channel_id)
            logger.info(f"retrieving uploaded videos for {channel_id} ... DONE")
            videos_hash = get_videos_hash(videos)
            logger.info(f"creating playlist for channel {channel_title} ({channel_id}) ...")
            created_playlist_id, added_video_count = create_channel_playlist(channel_id, videos, self.secrets_json_filepath)
            logger.info(f"-- {created_playlist_id} ({added_video_count}) ")
            logger.info(f"creating playlist for channel {channel_title} ({channel_id}) ... DONE")
            # cache data
            channel_data = ChannelInfo(
                channel_id=channel_id,
                channel_title=channel_title,
                playlist_id=created_playlist_id,
                videos_sha1hash=videos_hash,
                videos=videos
            )
            logger.info(f"caching data for channel {channel_title} ({channel_id}) ...")
            self._set_channel_data(channel_data)
            logger.info(f"caching data for channel {channel_title} ({channel_id}) ... DONE")
