import json
import datetime
import logging
from hashlib import sha1
from pathlib import Path

import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors

from .apis import YOUTUBE


logger = logging.getLogger(__name__)


SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]


def get_publish_date(item) -> datetime.datetime:
    published_at = item["snippet"]["publishedAt"]
    published_at = published_at.replace("Z", "+00:00")
    return datetime.datetime.fromisoformat(published_at)


def playlist_exists(channel_id) -> bool:
    exists = False
    return exists


def get_authorized_youtube_client(client_secrets_file: Path):
    api_service_name = "youtube"
    api_version = "v3"

    # Get credentials and create an API client
    flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
        str(client_secrets_file),
        SCOPES
    )
    credentials = flow.run_console()
    youtube = googleapiclient.discovery.build(
        api_service_name, api_version, credentials=credentials)
    return youtube


def create_channel_playlist(channel_id: str, videos: list[dict], client_secrets_file: Path) -> tuple[str, int]:
    assert videos, "No videos given!"

    # prepare youtube api client
    youtube = get_authorized_youtube_client(client_secrets_file)

    # This code creates a new, private playlist in the authorized user's channel.
    channel_title = videos[0]["snippet"].get("channelTitle", channel_id)

    # create new playlist
    new_playlist_title = f"{channel_title} - Journey down the Foxhole"
    request = youtube.playlists().insert(
        part="snippet,status",
        body=dict(
            snippet=dict(
                title=new_playlist_title,
                description=f"Follow '{channel_title}' down the foxhole... ({len(videos)}) reactions"
            ),
            status={
                "privacyStatus": "public"
            }
        )
    )
    response = request.execute()
    playlist_id = response["id"]
    logger.info(f"playlist_id={playlist_id}")
    logger.debug(response)
    # add all videos to playlist
    added_videos = 0
    for idx, video in enumerate(videos):
        logger.debug("adding video....")
        logger.debug(video["snippet"]["channelId"], video["snippet"]["channelTitle"], video["snippet"]["title"])
        request = youtube.playlistItems().insert(
            part="snippet,contentDetails",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video["snippet"]["resourceId"]["videoId"]
                    },
                    "position": idx,
                },
                "contentDetails": {
                    "note": f"Originally Published {video['snippet']['publishedAt']}",
                    "videoPublishedAt": video["snippet"]["publishedAt"],
                }
            }
        )
        response = request.execute()
        logger.debug(response)
        added_videos += 1
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
    request = YOUTUBE.playlistItems().list(
        part="snippet",
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
            if any(i in item["snippet"]["title"].lower() for i in ("babymetal", "ベビーメタル")):
                target_videos.append(item)
        request = YOUTUBE.playlistItems().list(
            part="snippet",
            playlistId=playlist_id,
            pageToken=next_page_token,
            maxResults=50,
        )
        response = request.execute()

    return channel_title, playlist_id, sorted(target_videos, key=get_publish_date)


def get_videos_hash(videos: list[dict]) -> str:
    return sha1(json.dumps(videos, sort_keys=True).encode("utf8")).hexdigest()


