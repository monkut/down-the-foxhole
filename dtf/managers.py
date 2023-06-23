import datetime
import json
import logging
import shutil
from math import ceil
from pathlib import Path
from typing import Generator, Optional

from . import settings
from .apis import YOUTUBE
from .definitions import ChannelInfo
from .functions import (
    create_channel_playlist,
    get_active_channel_section_playlistids,
    get_channel_videos,
    get_channelid_from_playlist,
    get_video_publishedat,
    get_videos_hash,
    update_active_playlists_channel_section_content,
    update_channel_playlist,
    window,
)

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
        self._active_section_playlistids_cache = []

    def set_credentials(self, secrets_filepath: Path) -> bool:
        assert secrets_filepath.exists(), f"not found: {secrets_filepath}"
        shutil.copy(secrets_filepath, self.secrets_json_filepath)
        return True

    def load_previous(self, channel_ids: Optional[list[str]] = None) -> None:
        # read channel cache
        # -- channels where the playlist successfully created
        logger.debug(f"storage_directory={self.storage_directory}")
        if channel_ids:
            for channel_id in channel_ids:
                item = self.storage_directory / channel_id
                if not item.exists():
                    logger.error(f"{item} cache does not exist, not loaded!")
                else:
                    logger.info(f"loading {item} ...")
                    raw_channel_data = json.loads(item.read_text(encoding="utf8"))
                    channel_data = ChannelInfo(**raw_channel_data)
                    self._data[channel_data.channel_id] = channel_data
                    logger.info(f"loading {item} ... DONE")
        else:
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

    def _get_latest_videopublishedat(self, channel_info: ChannelInfo) -> Optional[datetime.datetime]:
        latest_videopublishedat = None
        for video in channel_info.videos:
            content_details = video.get("contentDetails", None)
            if content_details:
                videopublishedat = content_details.get("videoPublishedAt", None)
                if videopublishedat:
                    if isinstance(videopublishedat, str):
                        # convert to datetime
                        videopublishedat = self._convert_api_datetime_to_datetime(videopublishedat)
                    if not latest_videopublishedat:
                        latest_videopublishedat = videopublishedat
                    elif videopublishedat > latest_videopublishedat:
                        latest_videopublishedat = videopublishedat
        return latest_videopublishedat

    def _get_channelinfo_sortedby_videopublishedat(
        self, gte_datetime: Optional[datetime.datetime] = None
    ) -> list[tuple[datetime.datetime, ChannelInfo]]:
        self.load_previous()  # loads values into _data
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

    def _convert_api_datetime_to_datetime(self, datetime_string: str) -> datetime.datetime:
        converted = datetime.datetime.fromisoformat(datetime_string.replace("Z", "+00:00"))
        converted.replace(tzinfo=datetime.timezone.utc)
        return converted

    def _get_channelinfo_by_channelids(self, channel_ids: list[str]) -> list[tuple[datetime.datetime, ChannelInfo]]:
        assert all(channel_ids), f"channel_ids list contains invalid id: {channel_ids}"
        self.load_previous(channel_ids=channel_ids)  # loads values into _data
        results = []
        for channel_info in self._data.values():
            if channel_info.channel_id in channel_ids:
                latest_videopublishedat = self._get_latest_videopublishedat(channel_info)
                data = (latest_videopublishedat, channel_info)
                results.append(data)
        return sorted(results, reverse=True)

    def _get_active_playlists_section_info(
        self, section_id: str = settings.ACTIVE_PLAYLISTS_SECTION_ID
    ) -> list[tuple[str, datetime.datetime, ChannelInfo]]:
        active_playlists = []  # latest_videopublishedat, channel_info
        if not self._active_section_playlistids_cache:
            section_playlistids = get_active_channel_section_playlistids(section_id, client_secrets_file=self.secrets_json_filepath)
            # update local cache
            self._active_section_playlistids_cache = section_playlistids
        else:
            section_playlistids = self._active_section_playlistids_cache
        for playlist_id in section_playlistids:
            # Get content of playlist (playlist contains content of 1 reactor channel)
            channel_id = get_channelid_from_playlist(playlist_id)
            if channel_id and channel_id != settings.CHANNEL_ID:
                channel_info_results = self._get_channelinfo_by_channelids([channel_id])
                assert len(channel_info_results) == 1, f"({channel_id}) len(channel_info_results)={len(channel_info_results)}, expected 1"
                latest_videopublishedat, channel_info = channel_info_results[0]
                logger.info(f"-- Retrieved ({channel_id}) {channel_info.channel_title} channel_info")
                active_playlists.append((playlist_id, latest_videopublishedat, channel_info))
            else:
                logger.warning(f"Invalid channel_id={channel_id} ... SKIPPING!")
        return active_playlists

    def _get_channelinfo_by_playlist_ids(self) -> dict[str, ChannelInfo]:
        self.load_previous()  # loads values into _data
        return {channel_info["playlist_id"]: channel_info for channel_info in self._data.values()}

    def _get_latest_videopublisheddatetime_from_channelinfo(self, channel_info: ChannelInfo) -> Optional[datetime.datetime]:
        latest_publishedat_datetime = None
        if channel_info.videos:
            latest_publishedat_datetime = sorted((get_video_publishedat(video) for video in channel_info.videos), reverse=True)[0]
        return latest_publishedat_datetime

    def _update_active_playlists_collection(self, playlists_ids: list[str], section_id: str = settings.ACTIVE_PLAYLISTS_SECTION_ID):
        # update to order playlists by newest -> oldest
        self.load_previous()  # make sure latest are loaded into memory
        ordered_playlists = []
        for channel_info in self._data.values():
            if channel_info.playlist_id in playlists_ids:
                latest_videopublishedat = self._get_latest_videopublishedat(channel_info)
                ordered_playlists.append((latest_videopublishedat, channel_info.playlist_id))
        assert all(pl in playlists_ids for _, pl in ordered_playlists)

        # order playlists by latest_videopublishedat and get latest 50
        ordered_playlists = list(sorted(ordered_playlists, reverse=True))
        ordered_playlist_ids = [playlist_id for _, playlist_id in ordered_playlists]
        update_playlist_ids = ordered_playlist_ids[: settings.CHANNELSECTION_UPDATE_MAX_PLAYLISTS]
        update_active_playlists_channel_section_content(section_id, update_playlist_ids, client_secrets_file=self.secrets_json_filepath)
        self._active_section_playlistids_cache = update_playlist_ids

    def _get_channel_new_videos(self, latest_videopublishedat: datetime.datetime, channel_info: ChannelInfo) -> list[dict]:
        logger.info(f"Retrieving new videos (>latest_videopublishedat {latest_videopublishedat}) {channel_info.channel_title} for update...")
        channel_id = channel_info.channel_id
        existing_video_ids = [v["snippet"]["resourceId"]["videoId"] for v in channel_info.videos]
        logger.debug(f"{channel_info.channel_title} {channel_info.channel_id} existing_video_ids={existing_video_ids}")
        channel_title, playlist_id, videos = get_channel_videos(channel_id=channel_id)
        new_videos = []
        for video in videos:
            video_id = video["snippet"]["resourceId"]["videoId"]
            logger.debug(f"video['snippet']['resourceId']['videoId']={video_id}")
            videopublishedat = self._convert_api_datetime_to_datetime(video["snippet"]["publishedAt"])
            if videopublishedat > latest_videopublishedat:
                if video_id not in existing_video_ids:
                    logger.info(f"-- {channel_info.channel_title} new video_id={video_id}")
                    new_videos.append(video)
            else:
                logger.info(
                    f"-- old video, skipping: new video_id={video_id}, videopublishedat({videopublishedat}) <= latest_videopublishedat({latest_videopublishedat})"
                )
        logger.info(
            f"Retrieving new videos (>latest_videopublishedat {latest_videopublishedat}) {channel_info.channel_title} for update... ({len(new_videos)}) DONE"
        )
        return new_videos

    def append_videos_to_playlist(self, playlist_id: str, videos: list[dict]):
        appended_videos = update_channel_playlist(playlist_id=playlist_id, videos=videos, client_secrets_file=self.secrets_json_filepath)
        return appended_videos

    def _get_existing_channels_to_check(self) -> list[tuple[datetime.datetime, ChannelInfo]]:
        channels_to_check = []
        existing_active_playlists_collection_info: list[tuple[str, datetime.datetime, ChannelInfo]] = self._get_active_playlists_section_info()
        for existing_playlist_id, latest_publishedat_datetime, channel_info in existing_active_playlists_collection_info:
            channels_to_check.append((latest_publishedat_datetime, channel_info))
        return channels_to_check

    def update(self, days: int = settings.DEFAULT_UPDATE_DAYS, channel_ids: Optional[list[str]] = None):
        now = datetime.datetime.now(datetime.timezone.utc)
        one_week_ago = now - datetime.timedelta(days=7)
        if channel_ids:
            # only check given channel_ids
            channels_to_check = self._get_channelinfo_by_channelids(channel_ids)
        else:
            gte_datetime = now - datetime.timedelta(days=days)
            channels_to_check = self._get_channelinfo_sortedby_videopublishedat(gte_datetime=gte_datetime)

            # add existing to head of list
            logger.info(f"updating channels_to_check with existing ... ")
            existing_channels_to_check = self._get_existing_channels_to_check()

            # filter out existing channels from channels_to_check
            existing_channel_ids = [ci.channel_id for _, ci in existing_channels_to_check]
            channels_to_check = existing_channels_to_check + [
                (latest, channel_info) for latest, channel_info in channels_to_check if channel_info.channel_id not in existing_channel_ids
            ]
            logger.info(f"updating channels_to_check with existing ... DONE")

        items_per_page = 5
        total_pages = ceil(len(channels_to_check) / items_per_page)
        for idx, page in enumerate(window(channels_to_check, n=items_per_page), 1):
            logger.info(f"updating ({len(channels_to_check)}) {idx}/{total_pages} ...")
            updated_playlist_ids = []
            for latest_videopublishedat, channel_info in page:
                channel_id = channel_info.channel_id
                # if channel has been updated in the last week, skip it!
                if channel_info.last_updated_datetime and channel_info.last_updated_datetime.replace(tzinfo=datetime.timezone.utc) >= one_week_ago:
                    logger.warning(
                        f"channel {channel_info.channel_title} {channel_id} last_updated_datetime({channel_info.last_updated_datetime}) >= days_ago({one_week_ago}) ... SKIPPING"
                    )
                    continue
                # check for new videos
                new_videos = self._get_channel_new_videos(latest_videopublishedat, channel_info)
                logger.info(f"Adding ({len(new_videos)}) videos to playlist:  {channel_info.channel_title} {channel_id} ...")
                playlist_id = channel_info.playlist_id
                if new_videos:
                    appended_videos = self.append_videos_to_playlist(playlist_id, new_videos)
                    channel_info.videos.extend(appended_videos)
                    # update channel_info
                    all_videos = channel_info.videos
                    videos_hash = get_videos_hash(all_videos)
                    logger.info(f"-- {playlist_id} ({len(appended_videos)}) ")
                    channel_title = channel_info.channel_title
                    logger.info(
                        f"Adding ({len(appended_videos)}/{len(new_videos)}) videos to playlist:  {channel_info.channel_title} {channel_id} ... DONE"
                    )

                    # update cache
                    channel_info.videos_sha1hash = videos_hash
                    channel_info.last_updated_datetime = datetime.datetime.now(datetime.timezone.utc)
                    logger.info(f"caching data for channel {channel_title} ({channel_id}) ...")
                    self._set_channel_data(channel_info)
                    logger.info(f"caching data for channel {channel_title} ({channel_id}) ... DONE")
                    updated_playlist_ids.append(playlist_id)
                else:
                    logger.warning(f"Adding ({len(new_videos)}) videos to playlist:  {channel_info.channel_title} {channel_id} ... NO VIDEOS FOUND!")

            if updated_playlist_ids:
                logger.info(f"-*-*- Updating Active Section {idx}/{total_pages} {settings.ACTIVE_PLAYLISTS_SECTION_ID} ...")
                self.update_active_journeys_section(updated_playlist_ids)
                logger.info(f"-*-*- Updating Active Section {idx}/{total_pages} {settings.ACTIVE_PLAYLISTS_SECTION_ID} ... DONE")

            else:
                logger.info(f"No updates found Active Section {idx}/{total_pages} not updated!")

    def update_active_journeys_section(self, playlist_ids_to_add: list[str], days: int = settings.DEFAULT_UPDATE_DAYS):
        now = datetime.datetime.now(datetime.timezone.utc)
        days_ago = now - datetime.timedelta(days=days)
        if not self._active_section_playlistids_cache:
            existing_active_playlists_collection_info: list[tuple[str, datetime.datetime, ChannelInfo]] = self._get_active_playlists_section_info()
            for existing_playlist_id, latest_publishedat_datetime, channel_info in existing_active_playlists_collection_info:
                if existing_playlist_id not in playlist_ids_to_add:
                    # check if still active
                    if latest_publishedat_datetime.replace(tzinfo=datetime.timezone.utc) >= days_ago:
                        logger.info(f"--- Keeping {channel_info.channel_title} in Active Journeys!")
                        playlist_ids_to_add.append(existing_playlist_id)
                    else:
                        logger.info(f"--- Removing {channel_info.channel_title} from Active Journeys!")
        else:
            playlist_ids_to_add.extend(self._active_section_playlistids_cache)
            # make unique and revert back to list
            playlist_ids_to_add = list(set(playlist_ids_to_add))

        logger.info(f" -- updated_playlist_ids={playlist_ids_to_add}")
        self._update_active_playlists_collection(playlist_ids_to_add)

    def discover(self, max_entries: int = settings.DISCOVER_MAX_ENTRIES, additional_query_args: Optional[list[str]] = None) -> list[tuple[str, str]]:
        # TODO: consider paging results!
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
            limit_exceeded = False
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
                                limit_exceeded = True
                                break
                if limit_exceeded:
                    break
        return results

    def process_channel(self, channel_id: str) -> Optional[tuple[datetime.datetime, ChannelInfo]]:
        channel_data = self.get_existing_playlist_data(channel_id)
        logger.debug(f"cached channel_ids={list(self._data.keys())}")
        results = None
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
                    last_updated_datetime=datetime.datetime.now(datetime.timezone.utc),
                )
                logger.info(f"caching data for channel {channel_title} ({channel_id}) ...")
                self._set_channel_data(channel_data)
                logger.info(f"caching data for channel {channel_title} ({channel_id}) ... DONE")

                channel_latest_publishedat = self._get_latest_videopublishedat(channel_info=channel_data)
                results = (channel_latest_publishedat, channel_data)
        return results
