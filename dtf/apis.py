import logging

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from apiclient.discovery import build

from . import settings


YOUTUBE = build('youtube', 'v3', developerKey=settings.YOUTUBE_API_KEY)

logger = logging.getLogger(__name__)

BOTO3_CONFIG = Config(connect_timeout=settings.BOTO3_CONNECT_TIMEOUT, retries={"max_attempts": 3})

S3_CLIENT = boto3.client("s3", config=BOTO3_CONFIG, endpoint_url=settings.AWS_SERVICE_ENDPOINTS["s3"])