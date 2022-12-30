"""Collect and process babymetal reaction videos"""
import sys
import logging
from pathlib import Path

from .managers import Collector
from . import settings


logging.basicConfig(stream=sys.stdout, level=logging.DEBUG, force=True, format="%(asctime)s [%(levelname)s] (%(name)s) %(funcName)s: %(message)s")
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("boto3").setLevel(logging.WARNING)
logging.getLogger("s3transfer").setLevel(logging.WARNING)
logging.getLogger("googleapiclient").setLevel(logging.WARNING)
logging.getLogger("requests_oauthlib").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def filepath(value) -> Path:
    p = Path(value).expanduser().resolve()
    assert p.exists(), f"not found: {p}"
    return p


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(title="commands", dest="command")
    discover_parser = subparsers.add_parser("discover")
    credentials_parser = subparsers.add_parser("setcredentials")
    credentials_parser.add_argument("-f", "--filepath", type=filepath, required=True, help="set the google api secrets json")
    createplaylist_parser = subparsers.add_parser("create")
    createplaylist_parser.add_argument("-c", "--channel-ids", nargs="+", required=True, dest="channel_ids", help="provide one or more channel ids to create playlists for")
    args = parser.parse_args()

    c = Collector()
    if args.command == "discover":
        results = c.discover()
        for channel_id, channel_title in results:
            print(channel_id, channel_title)
    elif args.command == "setcredentials":
        logger.info(f"setting credentials ...")
        c.set_credentials(args.filepath)
        logger.info(f"setting credentials ... DONE")
    elif args.command == "create":
        for channel_id in args.channel_ids:
            logger.info(f"processing {channel_id} ...")
            result = c.process_channel(channel_id)
            logger.info(f"processing {channel_id} ... DONE")
    else:
        parser.error(f"command not given: discover, create, setcredentials")

