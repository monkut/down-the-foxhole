import datetime
import functools
import json
import logging
import re
import sys
from hashlib import sha1
from itertools import islice
from pathlib import Path
from time import sleep
from typing import Generator, Iterable, Optional

import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors

from . import settings
from .apis import YOUTUBE

logger = logging.getLogger(__name__)


SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]


def get_video_publishedat(video: dict) -> Optional[datetime.datetime]:
    converted = None
    raw_value = video["snippet"].get("publishedAt")
    if raw_value:
        converted = datetime.datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        converted.replace(tzinfo=datetime.timezone.utc)
    return converted


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


@functools.cache
def get_authorized_youtube_client(client_secrets_file: Path):
    api_service_name = "youtube"
    api_version = "v3"

    # Get credentials and create an API client
    flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(str(client_secrets_file), SCOPES)
    credentials = flow.run_console()
    youtube = googleapiclient.discovery.build(api_service_name, api_version, credentials=credentials)
    return youtube


def get_published_datetimes(videos: list[dict]) -> list[datetime.datetime]:
    published_datetimes = []
    for video in videos:
        datetime_str = video["snippet"]["publishedAt"].replace("Z", "+00:00")
        d = datetime.datetime.fromisoformat(datetime_str)
        published_datetimes.append(d)
    return list(sorted(published_datetimes))


def window(seq: Iterable, n: int = 2):
    """
    Returns a sliding window (of width n) over data from the iterable
       s -> (s0,s1,...s[n-1]), (s1,s2,...,sn), ...
    """
    it = iter(seq)
    result = tuple(islice(it, n))
    if len(result) == n:
        yield result
    for elem in it:
        result = result[1:] + (elem,)
        yield result


def calculate_three_month_avg(videos: list[dict]) -> Optional[int]:
    """
    Calculate the '3mad' score
    Get the average number of days for the first 3 months since the *initial* published video
    """
    initial_three_month_avg = None
    videos_datetimes = get_published_datetimes(videos)
    if len(videos_datetimes) > 1:
        now = datetime.datetime.now(datetime.timezone.utc)
        initial_datetime = videos_datetimes[0]
        three_months_from_start = initial_datetime + datetime.timedelta(days=90)
        if three_months_from_start < now:
            all_delta_days = []
            for v1, v2 in window(videos_datetimes, n=2):
                if v2 <= three_months_from_start:
                    delta = v2 - v1
                    delta_days = delta.total_seconds() / 60 / 60 / 24
                    all_delta_days.append(delta_days)
            if all_delta_days:
                initial_three_month_avg = int(sum(days for days in all_delta_days) / len(all_delta_days))
    return initial_three_month_avg  # 3mad


def update_channel_playlist(playlist_id: str, videos: list, client_secrets_file: Path) -> list[dict]:
    assert videos, "No videos given!"

    # prepare youtube api client
    youtube = get_authorized_youtube_client(client_secrets_file)

    added = []
    for video in videos:
        resource_id = video["snippet"]["resourceId"]
        logger.debug(f"resource_id={resource_id}")
        request = youtube.playlistItems().insert(
            part="snippet,contentDetails",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": resource_id,
                },
                "contentDetails": {
                    "note": f"Originally Published {video['snippet']['publishedAt']}",
                    "videoPublishedAt": video["snippet"]["publishedAt"],
                },
            },
        )
        try:
            response = request.execute()
            logger.debug(f"response={response}")
            logger.info(f"playlist_id={playlist_id} video.resourceId={resource_id} Successfully Added!")
            added.append(video)
        except googleapiclient.errors.HttpError as e:
            logger.debug(f"e.status_code={e.status_code}")
            logger.debug(f"e.reason={e.reason}")
            logger.debug(f"e.error_details={e.error_details}")
            detailed_reason = None
            if e.error_details:
                detailed_reason = e.error_details[0].get("reason", None)
            logger.debug(f"detailed_reason={detailed_reason}")
    return added


def get_active_channel_section_playlistids(section_id: str, client_secrets_file: Path) -> list[str]:
    """
    Sample Response:

        {
            "kind": "youtube#channelSectionListResponse",
            "etag": "xxxx",
            "items": [
                {
                    "kind": "youtube#channelSection",
                    "etag": "xxxx",
                    "id": "{SECTION_ID}",
                    "contentDetails": {
                        "playlists": [
                            "{PLAYLIST_ID}",
                            "{PLAYLIST_ID}",
                            ...
                        ]
                    }
                }
            ]
        }
    """
    youtube = get_authorized_youtube_client(client_secrets_file)
    request = youtube.channelSections().list(
        part="contentDetails",
        id=section_id,
    )
    response = request.execute()
    # {
    #   "kind": "youtube#channelSectionListResponse",
    #   "etag": etag,
    #   "items": [
    #     {
    #   "kind": "youtube#channelSection",
    #   "etag": etag,
    #   "id": string,
    #   "contentDetails": {
    #     "playlists": [
    #       string
    #     ],
    #     "channels": [
    #       string
    #     ]
    #   }
    # }
    #   ]
    # }
    logger.debug(f"reponse={response}")
    assert len(response["items"]) == 1
    section_contentdetails = response["items"][0]["contentDetails"]
    section_playlists = section_contentdetails["playlists"]
    return section_playlists


def update_active_playlists_channel_section_content(section_id: str, playlists: list[str], client_secrets_file: Path):
    youtube = get_authorized_youtube_client(client_secrets_file)
    #     request = youtube.channelSections().update(
    #         part="contentDetails,id",
    #         body={
    #           "contentDetails": {
    #             "playlists": [
    #               ""
    #             ]
    #           }
    #         }
    #     )

    # getting error
    # HttpError 400 when requesting
    # https://youtube.googleapis.com/youtube/v3/channelSections?part=id%2CcontentDetails&alt=json
    # returned "Required". Details: "[{'message': 'Required', 'domain': 'global', 'reason': 'required'}]">
    request = youtube.channelSections().update(
        part="id,contentDetails,snippet",
        body={
            "id": section_id,
            "contentDetails": {
                "playlists": playlists,
                # "channels": [settings.CHANNEL_ID]
            },
            "snippet": {"type": "multiplePlaylists", "title": "Active Journeys"},
        },
    )
    response = request.execute()
    logger.debug(f"response={response}")


def get_channelid_from_playlist(playlist_id: str) -> str:
    logger.debug(f"playlist_id={playlist_id}")
    request = YOUTUBE.playlistItems().list(
        part="snippet,contentDetails,status",
        playlistId=playlist_id,
        maxResults=1,
    )
    channel_id = None
    try:
        response = request.execute()
        for item in response["items"]:
            if not channel_id:
                # get channel_title
                channel_title = item["snippet"]["channelTitle"]
                channel_id = item["snippet"].get("videoOwnerChannelId", None)
                logger.info(f"-- {channel_title} channel_id={channel_id}")
    except googleapiclient.errors.HttpError as e:
        if e.status_code == 404:
            logger.warning(f"playlist_id not found: {playlist_id}")
        else:
            raise

    return channel_id


def create_channel_playlist(channel_id: str, videos: list[dict], client_secrets_file: Path) -> tuple[str, list[dict]]:
    assert videos, "No videos given!"

    # prepare youtube api client
    youtube = get_authorized_youtube_client(client_secrets_file)

    # This code creates a new, private playlist in the authorized user's channel.
    channel_title = videos[0]["snippet"].get("channelTitle", channel_id)

    # create new playlist
    # -- calculate 3mad
    threemad_display_str = ""
    threemad_result = calculate_three_month_avg(videos)
    if threemad_result:
        threemad_display_str = f"3MAD={threemad_result}"

    new_playlist_title = f"{channel_title} {settings.PLAYLIST_SUBTITLE} {threemad_display_str}".strip()
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
            elif e.status_code == 403 and detailed_reason == "quotaExceeded":
                logger.error(f"403 {detailed_reason} {e.reason}")
                logger.error("try again later, exiting...")
                sys.exit(1)
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


def chunker(seq: Iterable, size: int) -> Generator:
    return (seq[pos : pos + size] for pos in range(0, len(seq), size))


def _filter_videos(channel_title: str, videos: list[dict], minimum_duration_seconds: int = settings.MINIMUM_VIDEO_DURATION_SECONDS) -> list[dict]:
    """Filter out blocked and short videos"""
    assert videos, f"videos not defined, len(videos)={len(videos)}"
    keyed_videos = {v["contentDetails"]["videoId"]: v for v in videos}
    video_ids = set(keyed_videos.keys())
    skipped_video_ids = set()
    processed_ids = set()
    logger.info(f"{channel_title} retrieving video details ...")
    max_chunk_size = 50
    for video_ids_chunk in chunker(list(video_ids), max_chunk_size):
        video_ids_str = ",".join(list(video_ids_chunk))
        request = YOUTUBE.videos().list(
            part="snippet,contentDetails,status",
            id=video_ids_str,
            maxResults=50,
        )
        response = request.execute()

        next_page_token = True  # Allow processing for initial response
        while next_page_token:
            next_page_token = response.get("nextPageToken", None)
            for item in response["items"]:
                processed_ids.add(item["id"])  # assuming 'id' the same as contentDetail.videoId
                duration_string = item["contentDetails"].get("duration")  # format: ISO 8601
                if "regionRestriction" in item["contentDetails"] and "blocked" in item["contentDetails"]["regionRestriction"]:
                    logger.warning(f"blocked video found: {item['id']} {item['snippet']['title']}")
                    skipped_video_ids.add(item["id"])
                elif item["status"].get("uploadStatus") == "rejected":
                    logger.warning(f"rejected video found: {item['id']} {item['snippet']['title']}")
                    skipped_video_ids.add(item["id"])
                elif duration_string:
                    duration_seconds = parse_duration(duration_string)
                    if duration_seconds and duration_seconds < minimum_duration_seconds:
                        logger.warning(f"skipping short duration ({duration_seconds}) video....")
                        skipped_video_ids.add(item["id"])
            if next_page_token:
                request = YOUTUBE.videos().list(
                    part="snippet,contentDetails,status",
                    id=video_ids_str,
                    pageToken=next_page_token,
                    maxResults=50,
                )
                response = request.execute()
                sleep(0.25)  # to reduce rate-limit responses
    logger.info(f"{channel_title} retrieving video details ... DONE")
    valid_video_ids = video_ids - skipped_video_ids
    logger.debug(f"len(video_ids)={len(video_ids)}")
    logger.debug(f"len(skipped_video_ids)={len(skipped_video_ids)}")
    logger.debug(f"len(valid_video_ids)={len(valid_video_ids)}")
    return [keyed_videos[vid] for vid in valid_video_ids]


def get_channel_videos(channel_id: str) -> tuple[str, str, list[dict]]:
    """Collect all target videos in channel and return ordered list"""
    target_videos = []
    # convert channel_id to channel's upload videos playlist_id
    # https://stackoverflow.com/a/27872244/24718
    # UC0v-tlzsn0QZwJnkXYZ -> UU0v-tlzsn0QZwJnkXYZ
    playlist_id = "UU" + channel_id[2:]

    # get 'uploads' playlist for channel
    logger.info(f"retrieving videos for channel: {channel_id}")
    logger.debug(f"playlist_id={playlist_id}")
    request = YOUTUBE.playlistItems().list(
        part="snippet,contentDetails,status",
        playlistId=playlist_id,
        maxResults=50,
    )
    channel_title = None
    videos = []
    try:
        response = request.execute()
        next_page_token = True  # Allow processing for initial response
        while next_page_token:
            next_page_token = response.get("nextPageToken", None)
            for item in response["items"]:
                if not channel_title:
                    # get channel_title
                    channel_title = item["snippet"]["channelTitle"]
                if any(i in item["snippet"]["title"].lower() for i in settings.VIDEO_TITLE_TARGET_TEXT):
                    target_videos.append(item)
            if next_page_token:
                request = YOUTUBE.playlistItems().list(
                    part="snippet,contentDetails",
                    playlistId=playlist_id,
                    pageToken=next_page_token,
                    maxResults=50,
                )
                response = request.execute()
                sleep(0.25)  # to reduce rate-limit responses
        if target_videos:
            # remove 'blocked' and 'short' videos
            filtered_target_videos = _filter_videos(channel_title, videos=target_videos)
            videos = sorted(filtered_target_videos, key=get_publish_date)

    except googleapiclient.errors.HttpError as e:
        if e.status_code == 404:
            logger.warning(f"playlist_id not found: {playlist_id}")
        else:
            raise

    return channel_title, playlist_id, videos


def get_videos_hash(videos: list[dict]) -> str:
    return sha1(json.dumps(videos, sort_keys=True).encode("utf8")).hexdigest()
