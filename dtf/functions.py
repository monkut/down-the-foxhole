import datetime
import functools
import json
import logging
import re
from hashlib import sha1
from pathlib import Path
from time import sleep

import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors

from . import settings
from .apis import YOUTUBE

logger = logging.getLogger(__name__)


SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]


def parse_duration(duration_str) -> int:
    match = re.match(
        r"P((?P<years>\d+)Y)?((?P<months>\d+)M)?((?P<weeks>\d+)W)?((?P<days>\d+)D)?(T((?P<hours>\d+)H)?((?P<minutes>\d+)M)?((?P<seconds>\d+)S)?)?",
        duration_str,
    ).groupdict()
    return (
        int(match["years"] or 0) * 365 * 24 * 3600
        + int(match["months"] or 0) * 30 * 24 * 3600
        + int(match["weeks"] or 0) * 7 * 24 * 3600
        + int(match["days"] or 0) * 24 * 3600
        + int(match["hours"] or 0) * 3600
        + int(match["minutes"] or 0) * 60
        + int(match["seconds"] or 0)
    )


def get_publish_date(item) -> datetime.datetime:
    published_at = item["snippet"]["publishedAt"]
    published_at = published_at.replace("Z", "+00:00")
    return datetime.datetime.fromisoformat(published_at)


def playlist_exists(channel_id) -> bool:
    exists = False
    return exists


@functools.cache
def get_authorized_youtube_client(client_secrets_file: Path):
    api_service_name = "youtube"
    api_version = "v3"

    # Get credentials and create an API client
    flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(str(client_secrets_file), SCOPES)
    credentials = flow.run_console()
    youtube = googleapiclient.discovery.build(api_service_name, api_version, credentials=credentials)
    return youtube


def create_channel_playlist(channel_id: str, videos: list[dict], client_secrets_file: Path) -> tuple[str, list[dict]]:
    assert videos, "No videos given!"

    # prepare youtube api client
    youtube = get_authorized_youtube_client(client_secrets_file)

    # This code creates a new, private playlist in the authorized user's channel.
    channel_title = videos[0]["snippet"].get("channelTitle", channel_id)

    # create new playlist
    new_playlist_title = f"{channel_title} 🤘🏻🦊🤘🏻 Journey down the Foxhole"
    request = youtube.playlists().insert(
        part="snippet,status",
        body=dict(
            snippet=dict(title=new_playlist_title, description=f"Follow '{channel_title}' down the foxhole... ({len(videos)}) reactions"),
            status={"privacyStatus": "public"},
        ),
    )
    retries = 0
    while True:
        try:
            response = request.execute()
            playlist_id = response["id"]
            logger.info(f"playlist_id={playlist_id} Successfully created!")
            break
        except googleapiclient.errors.HttpError as e:
            logger.debug(f"e.status_code={e.status_code}")
            logger.debug(f"e.reason={e.reason}")
            logger.debug(f"e.error_details={e.error_details}")
            detailed_reason = None
            if e.error_details:
                detailed_reason = e.error_details[0].get("reason", None)
            logger.debug(f"detailed_reason={detailed_reason}")
            if retries <= settings.MAX_RETRIES and e.status_code == 429 and detailed_reason == "RATE_LIMIT_EXCEEDED":
                logger.info(f"Re-trying Playlist Creation: {channel_title} {channel_id}")
                retries += 1
                logger.warning(f"(429) RATE_LIMIT_EXCEEDED -- retrying ({retries})...")
                sleep_seconds = settings.BASE_SLEEP_SECONDS**retries
                if sleep_seconds > settings.MAX_SLEEP_SECONDS:
                    logger.debug(f"sleep_seconds({sleep_seconds}) > MAX_SLEEP_SECONDS({settings.MAX_SLEEP_SECONDS})")
                    logger.debug(f"setting sleep_seconds to {settings.MAX_SLEEP_SECONDS}")
                    sleep_seconds = settings.MAX_SLEEP_SECONDS
                logger.info(f"sleeping {sleep_seconds}s ...")
                sleep(sleep_seconds)
            elif retries > settings.MAX_RETRIES:
                logger.error(f"MAX_RETRIES({settings.MAX_RETRIES}) exceeded!")
                raise
            else:  # other exception
                raise  # re-raise exception

    # add all videos to playlist
    added_videos = []
    for idx, video in enumerate(videos):
        logger.debug("adding video....")
        logger.debug(f"{video['snippet']['channelId']} {video['snippet']['channelTitle']} {video['snippet']['title']}")
        request = youtube.playlistItems().insert(
            part="snippet,contentDetails",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": video["snippet"]["resourceId"]["videoId"]},
                    "position": idx,
                },
                "contentDetails": {
                    "note": f"Originally Published {video['snippet']['publishedAt']}",
                    "videoPublishedAt": video["snippet"]["publishedAt"],
                },
            },
        )
        try:
            request.execute()
            added_videos.append(video)
            sleep(0.5)
        except googleapiclient.errors.HttpError as e:
            logger.exception(e)
    sleep(1.0)
    return playlist_id, added_videos


def get_channel_videos(channel_id: str) -> tuple[str, str, list[dict]]:
    """Collect all babymetal videos in channel and return ordered list"""
    target_videos = []
    # convert channel_id to playlist_id
    # https://stackoverflow.com/a/27872244/24718
    # UC0v-tlzsn0QZwJnkXYZ -> UU0v-tlzsn0QZwJnkXYZ
    playlist_id = "UU" + channel_id[2:]

    # get 'uploads' playlist for channel
    logger.info(f"retrieving videos for channel: {channel_id}")
    logger.debug(f"playlist_id={playlist_id}")
    request = YOUTUBE.playlistItems().list(
        part="snippet,contentDetails",
        playlistId=playlist_id,
        maxResults=50,
    )
    response = request.execute()
    channel_title = None
    while "nextPageToken" in response and response["nextPageToken"]:
        next_page_token = response["nextPageToken"]
        for item in response["items"]:
            if not channel_title:
                # get channel_title
                channel_title = item["snippet"]["channelTitle"]
            duration_string = item["contentDetails"].get("duration")  # format: ISO 8601
            duration_seconds = None
            if duration_string:
                duration_seconds = parse_duration(duration_string)
            if duration_seconds and duration_seconds < 60:  # NOTE: doesn't work, since duration information is not included...
                logger.warning(f"skipping short duration video....")
                logger.debug(item)
            elif any(i in item["snippet"]["title"].lower() for i in ("babymetal", "baby metal", "ベビーメタル")):
                target_videos.append(item)
        request = YOUTUBE.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=playlist_id,
            pageToken=next_page_token,
            maxResults=50,
        )
        response = request.execute()
        sleep(0.25)  # to reduce rate-limit responses

    return channel_title, playlist_id, sorted(target_videos, key=get_publish_date)


def get_videos_hash(videos: list[dict]) -> str:
    return sha1(json.dumps(videos, sort_keys=True).encode("utf8")).hexdigest()
