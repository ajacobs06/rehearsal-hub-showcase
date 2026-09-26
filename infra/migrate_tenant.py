"""One-off copy of production data from the old (UoB) subscription to the new one.

Copies every blob in the tracks container, then every document in every Cosmos container. Copied
blobs get new ETags, and the API refuses links to a file whose ETag differs from the one recorded
when it passed the upload checks, so each song's `files.<kind>.etag` is rewritten to the new blob's.
Safe to re-run: blobs are overwritten and documents upserted (in that order, so ETags always match).

Needs `az login` to both tenants, and temporary data roles for you on both sides (see
infra/MIGRATION.md). Run from api/ so the Azure SDKs from requirements.txt are available:

    cd api && .venv/bin/python ../infra/migrate_tenant.py --dry-run \\
        --src-subscription <old subscription id> --src-cosmos https://<old>.documents.azure.com:443/ \\
        --src-storage https://<old>.blob.core.windows.net/ \\
        --dst-subscription <new subscription id> --dst-cosmos https://<new>.documents.azure.com:443/ \\
        --dst-storage https://<new>.blob.core.windows.net/
"""

import argparse
import sys

from azure.cosmos import CosmosClient
from azure.identity import AzureCliCredential
from azure.storage.blob import BlobServiceClient, ContentSettings

CONTAINERS = ["members", "groups", "songs", "progress", "rehearsals", "feedback"]
COSMOS_SYSTEM = {"_rid", "_self", "_etag", "_attachments", "_ts"}


def blob_path(song_id: str, kind: str) -> str:
    """Same as api/songs.py."""
    return f"{song_id}/{'score.pdf' if kind == 'score' else f'{kind}.mp3'}"


def copy_blobs(src, dst, dry_run: bool) -> dict[str, str]:
    """Copy every current blob; return {path: new ETag}."""
    etags: dict[str, str] = {}
    total = 0
    for blob in src.list_blobs():
        total += blob.size
        if dry_run:
            print(f"  would copy {blob.name} ({blob.size:,} bytes)")
            continue
        data = src.download_blob(blob.name).readall()
        # BlobClient.upload_blob returns the new properties (ContainerClient's returns a client).
        result = dst.get_blob_client(blob.name).upload_blob(
            data,
            overwrite=True,
            content_settings=ContentSettings(content_type=blob.content_settings.content_type),
        )
        etags[blob.name] = result["etag"]
        print(f"  copied {blob.name} ({blob.size:,} bytes)")
    print(f"  {total / 1e6:.1f} MB")
    return etags


def fix_song_etags(song: dict, etags: dict[str, str]) -> list[str]:
    """Point each recorded file at its copied blob. Returns problems found."""
    problems = []
    for kind, info in (song.get("files") or {}).items():
        path = blob_path(song["id"], kind)
        if path not in etags:
            problems.append(f"song {song['id']} ({song.get('title')}) records {kind} but {path} was not copied")
        elif info.get("etag") is not None:
            info["etag"] = etags[path]
    return problems


def copy_documents(src_db, dst_db, etags: dict[str, str], dry_run: bool) -> list[str]:
    problems = []
    for name in CONTAINERS:
        src = src_db.get_container_client(name)
        dst = dst_db.get_container_client(name)
        docs = [{k: v for k, v in d.items() if k not in COSMOS_SYSTEM} for d in src.read_all_items()]
        for doc in docs:
            if name == "songs" and not dry_run:
                problems += fix_song_etags(doc, etags)
            if not dry_run:
                dst.upsert_item(doc)
        copied = sum(1 for _ in dst.read_all_items()) if not dry_run else "-"
        print(f"  {name}: {len(docs)} in source, {copied} in destination")
        if not dry_run and copied < len(docs):
            problems.append(f"{name}: destination has fewer documents than the source")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for side in ("src", "dst"):
        ap.add_argument(f"--{side}-subscription", required=True, help="Picks the az login (and tenant) for this side")
        ap.add_argument(f"--{side}-cosmos", required=True, help="Cosmos account endpoint")
        ap.add_argument(f"--{side}-storage", required=True, help="Blob endpoint of the prod storage account")
    ap.add_argument("--database", default="rehearsal-hub")
    ap.add_argument("--container", default="tracks")
    ap.add_argument("--dry-run", action="store_true", help="Read the source and report; write nothing")
    args = ap.parse_args()

    # By subscription, not tenant: each side is a different az login, and a tenant alone would use
    # whichever account is currently active.
    src_cred = AzureCliCredential(subscription=args.src_subscription)
    dst_cred = AzureCliCredential(subscription=args.dst_subscription)
    src_blobs = BlobServiceClient(args.src_storage, credential=src_cred).get_container_client(args.container)
    dst_blobs = BlobServiceClient(args.dst_storage, credential=dst_cred).get_container_client(args.container)
    src_db = CosmosClient(args.src_cosmos, credential=src_cred).get_database_client(args.database)
    dst_db = CosmosClient(args.dst_cosmos, credential=dst_cred).get_database_client(args.database)

    print("Blobs:")
    etags = copy_blobs(src_blobs, dst_blobs, args.dry_run)
    print("Documents:")
    problems = copy_documents(src_db, dst_db, etags, args.dry_run)

    for p in problems:
        print(f"PROBLEM: {p}", file=sys.stderr)
    print("Dry run: nothing written." if args.dry_run else "Done." if not problems else "Finished with problems.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
