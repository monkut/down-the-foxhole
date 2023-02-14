import logging
import os

logger = logging.getLogger(__name__)

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", None)
assert YOUTUBE_API_KEY, f"YOUTUBE_API_KEY not set!"

DEFAULT_S3_BUCKET = "tests-bucket"
S3_BUCKET = os.getenv("S3_BUCKET", DEFAULT_S3_BUCKET)
PREVIOUS_S3_KEY = os.getenv("previous.pkl")


BOTO3_CONNECT_TIMEOUT = 15
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "ap-northeast-1")
AWS_PROFILE = os.getenv("AWS_PROFILE", "default")

DEFAULT_S3_SERVICE_ENDPOINT = f"https://s3.{AWS_DEFAULT_REGION}.amazonaws.com"
AWS_SERVICE_ENDPOINTS = {
    "s3": os.getenv("S3_SERVICE_ENDPOINT", DEFAULT_S3_SERVICE_ENDPOINT),
}
logger.info(f"AWS_SERVICE_ENDPOINTS: {AWS_SERVICE_ENDPOINTS}")


IGNORE_CHANNEL_IDS = (
    "UC0v-tlzsn0QZwJnkiaUSJVQ",
    "UCpD0Xw403VhhdackcEEBruA",
    "UC-DkGegRWmh5JjkcqKgyIeA",
    "UCIUA7-MNA9NyrpimQo7Dw8g",
    "UC5CQdR2PORZOJLwIZkGQdQw",
)

MAX_RETRIES = 8
BASE_SLEEP_SECONDS = 10
MAX_SLEEP_SECONDS = int(1.5 * 60 * 60)  # 1.5 hours

DEFAULT_UPDATE_DAYS = 90

MINIMUM_VIDEO_DURATION_SECONDS = 90
CHANNEL_QUERY_STRING = "babymetal reaction"  # defines the query string to use when searching for channels
VIDEO_TITLE_TARGET_TEXT = ("babymetal", "baby metal", "ベビーメタル")  # "OR" Pick up videos containing any of the text defined here!
