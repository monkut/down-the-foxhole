"""Collect and process babymetal reaction videos"""
import logging
import sys
from pathlib import Path

from . import settings
from .managers import Collector

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
    discover_parser = subparsers.add_parser("discover", help="discover new channel-ids given set search criteria ")
    discover_parser.add_argument(
        "-a",
        "--additional-query",
        dest="additional_query_args",
        nargs="+",
        default=None,
        help="if given, additional arguments are passed to the query",
    )
    discover_parser.add_argument("-m", "--max-results", dest="max_results", type=int, default=25, help="Set the max unused reactors (default=25)")
    credentials_parser = subparsers.add_parser("setcredentials")
    credentials_parser.add_argument("-f", "--filepath", type=filepath, required=True, help="set the google api secrets json")
    createplaylist_parser = subparsers.add_parser("create", help="Create playlists for given channel-ids")
    createplaylist_parser.add_argument(
        "-c", "--channel-ids", nargs="+", required=True, dest="channel_ids", help="provide one or more channel ids to create playlists for"
    )
    update_parser = subparsers.add_parser("update")
    update_parser.add_argument(
        "--days",
        "-d",
        required=False,
        default=settings.DEFAULT_UPDATE_DAYS,
        type=int,
        help="Number of days since last reaction to consider for updating",
    )
    update_parser.add_argument(
        "--channel-ids", dest="channel_ids", required=False, default=None, nargs="+", help="If given, only provided channel_ids will be updated"
    )
    autocreate_parser = subparsers.add_parser("autocreate", help="auto-discover and create playlists")
    args = parser.parse_args()

    c = Collector()
    valid_commands = ("discover", "create", "setcredentials", "update")
    if args.command == "discover":
        results = c.discover(args.max_results, additional_query_args=args.additional_query_args)
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
    elif args.command == "autocreate":
        results = c.discover()
        logger.info(f"discovered {len(results)} *new* channels")
        for channel_id, _ in results:
            logger.info(f"processing {channel_id} ...")
            result = c.process_channel(channel_id)
            logger.info(f"processing {channel_id} ... DONE")
    elif args.command == "update":
        c.update(days=args.days, channel_ids=args.channel_ids)
    else:
        parser.error(f"command not given: {valid_commands}")
