import datetime
import json
import logging
import shutil
from pathlib import Path
from typing import Generator, Optional

from . import settings
from .apis import YOUTUBE
from .definitions import ChannelInfo
from .functions import create_channel_playlist, get_channel_videos, get_videos_hash

logger = logging.getLogger(__name__)


class Collector:
    def __init__(self, query_string: str = settings.CHANNEL_QUERY_STRING, storage_directory: Path = Path("~/.dtf").expanduser()):
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

    def load_previous(self):
        # read channel cache
        # -- channels where the playlist successfully created
        logger.debug(f"storage_directory={self.storage_directory}")
        for item in self.storage_directory.glob("*"):
            if item.stem == "secrets":
                continue  # skip credentials file
            logger.info(f"loading {item} ...")
            raw_channel_data = json.loads(item.read_text(encoding="utf8"))
            channel_data = ChannelInfo(**raw_channel_data)
            self._data[channel_data.channel_id] = channel_data
            logger.info(f"loading {item} ... DONE")

    def get_existing_playlist_data(self, channel_id: Optional[str] = None) -> Optional[ChannelInfo]:
        self.load_previous()
        if channel_id:
            result = self._data.get(channel_id, None)
        else:
            result = self._data
        return result

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

    def search_for_reactors(self, additional_query_args: Optional[list[str]]) -> Generator:

        query_string = self.query_string
        if additional_query_args:
            for arg in additional_query_args:
                query_string += f" {arg}"
        logger.info(f"query_string='{query_string}'")
        request = YOUTUBE.search().list(
            part="snippet",
            # 検索したい文字列を指定
            q=query_string,
            order="viewCount",
            type="video",
            maxResults=50,
        )
        response = request.execute()
        yield response
        while "nextPageToken" in response and response["nextPageToken"]:
            next_page_token = response["nextPageToken"]
            request = YOUTUBE.search().list(
                part="snippet",
                # 検索したい文字列を指定
                q=self.query_string,
                order="viewCount",
                type="video",
                pageToken=next_page_token,
                maxResults=50,
            )
            response = request.execute()
            yield response

    def _get_latest_videopublishedat(self, channel_info: dict) -> Optional[datetime.datetime]:
        latest_videopublishedat = None
        for video in channel_info["videos"]:
            content_details = video.get("contentDetails", None)
            if content_details:
                videopublishedat = content_details.get("videoPublishedAt", None)
                if videopublishedat:
                    if not latest_videopublishedat:
                        latest_videopublishedat = videopublishedat
                    elif videopublishedat > latest_videopublishedat:
                        latest_videopublishedat = videopublishedat
        return latest_videopublishedat

    def _get_channelinfo_sortedby_videopublishedat(self, gte_datetime: Optional[datetime.datetime] = None) -> list[tuple[datetime.datetime, dict]]:
        self.load_previous()
        results = []
        for channel_info in self._data.values():
            latest_videopublishedat = self._get_latest_videopublishedat(channel_info)
            if latest_videopublishedat:
                data = (latest_videopublishedat, channel_info)
                if gte_datetime and latest_videopublishedat >= gte_datetime:
                    results.append(data)
                else:
                    results.append(data)
        return sorted(results, reverse=True)

    def _get_new_videos(self, latest_videopublishedat: datetime.datetime, channel_info: dict) -> list[dict]:
        raise NotImplementedError

    def append_videos_to_playlist(self, playlist_id: str, videos: list[dict]):
        raise NotImplementedError

    def update(self, days: int = settings.DEFAULT_UPDATE_DAYS):
        now = datetime.datetime.now(datetime.timezone.utc)
        gte_datetime = now - datetime.timedelta(days=days)
        channels_to_check = self._get_channelinfo_sortedby_videopublishedat(gte_datetime=gte_datetime)
        for latest_videopublishedat, channel_info in channels_to_check:
            # check for new videos
            new_videos = self._get_new_videos(latest_videopublishedat, channel_info)
            logger.info(f"Adding ({len(new_videos)}) videos to playlist:  {channel_info['channel_title']} {channel_info['channel_id']}")
            self.append_videos_to_playlist(channel_info["playlist_id"], new_videos)
            raise NotImplementedError

    def discover(self, max_entries: int = 25, additional_query_args: Optional[list[str]] = None) -> list[tuple[str, str]]:
        results = []
        max_loop = 5
        loop_count = 0
        while len(results) < max_entries:
            loop_count += 1
            if loop_count >= max_loop:
                logger.warning(f"loop_count({loop_count}) >= max_loop({max_loop}) count met/exceeded, breaking!")
                break
            responses = self.search_for_reactors(additional_query_args)
            self.load_previous()
            for response in responses:
                for item in response["items"]:
                    # get channel_id and retrieve all target videos
                    channel_id = item["snippet"]["channelId"]
                    channel_title = item["snippet"]["channelTitle"]
                    if channel_id not in settings.IGNORE_CHANNEL_IDS:
                        channel_info = (channel_id, channel_title)
                        if channel_info in results:
                            logger.debug(f"already found, {channel_id}")
                        elif channel_id in self._data:
                            logger.info(f"playlist already created, skipping: {channel_id} {channel_title}")
                        else:
                            results.append(channel_info)
                            if len(results) >= max_entries:
                                logger.info(f"max_entries({max_entries}) found, breaking")
                                break
        return results

    def process_channel(self, channel_id: str):
        channel_data = self.get_existing_playlist_data(channel_id)
        logger.debug(f"cached channel_ids={list(self._data.keys())}")
        if channel_id in settings.IGNORE_CHANNEL_IDS:
            logger.info(f"skipping channel in ignore list: {channel_id}")
        elif channel_data:
            logger.info(f"playlist already created for: {channel_id} {channel_data.channel_title}")
            logger.info(f" - cache stored in {self.storage_directory}")
        else:
            logger.info(f"retrieving uploaded videos for {channel_id} ...")
            channel_title, channel_playlist_id, videos = get_channel_videos(channel_id)
            logger.info(f"retrieving uploaded videos for {channel_id} ... DONE")
            if not videos:
                logger.error(f"No videos found for channel: {channel_id} {channel_title}")
            else:
                logger.info(f"creating playlist for channel {channel_title} ({channel_id}) ...")
                created_playlist_id, added_videos = create_channel_playlist(channel_id, videos, self.secrets_json_filepath)
                videos_hash = get_videos_hash(added_videos)
                logger.info(f"-- {created_playlist_id} ({len(added_videos)}) ")
                logger.info(f"creating playlist for channel {channel_title} ({channel_id}) ... DONE")
                # cache data
                channel_data = ChannelInfo(
                    channel_id=channel_id,
                    channel_title=channel_title,
                    playlist_id=created_playlist_id,
                    videos_sha1hash=videos_hash,
                    videos=added_videos,
                )
                logger.info(f"caching data for channel {channel_title} ({channel_id}) ...")
                self._set_channel_data(channel_data)
                logger.info(f"caching data for channel {channel_title} ({channel_id}) ... DONE")
