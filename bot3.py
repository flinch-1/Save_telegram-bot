import json
import os
import logging
import asyncio
from telethon import TelegramClient
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logging.getLogger("telethon").setLevel(logging.DEBUG)

# File to store credentials
CREDENTIALS_FILE = "credentials.json"

async def authenticate(client, phone_number):
    """Authenticate the user and connect the client."""
    if not client.is_connected():
        await client.connect()

    if not await client.is_user_authorized():
        logging.info("Client not authorized. Sending code...")
        await client.start(phone=phone_number)
        logging.info("Authorization complete!")

async def post_media_to_group(client, target_group, media_path):
    """Post downloaded media to a specified target group."""
    try:
        # Sending the downloaded media file to the target group
        await client.send_file(target_group, media_path)
        logging.info(f"Successfully sent media {media_path} to {target_group}")
    except Exception as e:
        logging.error(f"Failed to send media {media_path} to {target_group}: {e}")

async def harvest_and_post_media(client):
    """Harvest media from selected groups and post it to another group."""
    # Prompt for the target group to send the media to (group you own)
    target_group_input = input("Enter the target group username or ID to post media to: ").strip()

    # Get the list of groups you are a member of
    dialogs = await client.get_dialogs()

    # Filter out only groups/channels
    groups = [dialog for dialog in dialogs if dialog.is_group or dialog.is_channel]

    # If no groups/channels are found, notify the user
    if not groups:
        logging.error("You are not a member of any groups or channels.")
        return

    # Display available groups for the user to choose from
    print("You are a member of the following groups:")
    for idx, group in enumerate(groups, start=1):
        print(f"{idx}. {group.name}")

    # Prompt the user to select the groups they want to harvest media from
    selected_indices = input("Enter the numbers of the groups you want to harvest media from (comma-separated): ").split(",")
    selected_indices = [int(idx.strip()) - 1 for idx in selected_indices]

    # Ensure selected indices are valid
    selected_groups = [groups[idx] for idx in selected_indices if 0 <= idx < len(groups)]

    # If no valid groups are selected, notify the user
    if not selected_groups:
        logging.error("No valid groups selected.")
        return

    # Proceed with harvesting media from selected groups
    for group in selected_groups:
        try:
            # Ensure group media directory exists
            group_dir = f"media/{group.name}"
            os.makedirs(group_dir, exist_ok=True)

            logging.info(f"Fetching messages from group: {group.name}")
            offset_id = 0  # Start from the most recent message
            limit = 100  # Number of messages to fetch in one batch
            photo_count = 0
            video_count = 0

            # First pass: Count the number of photos and videos
            while True:
                messages = await client.get_messages(group.id, offset_id=offset_id, limit=limit)
                if not messages:
                    break  # No more messages to fetch

                for message in messages:
                    if message.media:
                        # Count photos and videos
                        if isinstance(message.media, MessageMediaPhoto):
                            photo_count += 1
                        elif isinstance(message.media, MessageMediaDocument):
                            if hasattr(message.media.document, 'mime_type') and 'video' in message.media.document.mime_type:
                                video_count += 1

                # Update offset_id to fetch older messages in the next iteration
                offset_id = messages[-1].id

            # Log the counts of media
            logging.info(f"Found {photo_count} photos and {video_count} videos in group: {group.name}")

            # Ask the user how many photos and videos to download
            download_photos = int(input(f"How many photos to download from {group.name} (0 to skip): ").strip())
            download_videos = int(input(f"How many videos to download from {group.name} (0 to skip): ").strip())

            # Ensure the user doesn't try to download more than available media
            download_photos = min(download_photos, photo_count)
            download_videos = min(download_videos, video_count)

            logging.info(f"Downloading {download_photos} photos and {download_videos} videos from group: {group.name}")

            # Second pass: Download the selected number of photos and videos
            downloaded_photos = 0
            downloaded_videos = 0
            offset_id = 0  # Reset the offset_id to start from the latest message again

            while True:
                messages = await client.get_messages(group.id, offset_id=offset_id, limit=limit)
                if not messages:
                    break  # No more messages to fetch

                for message in messages:
                    if message.media:
                        # Download photos if the user wants them
                        if isinstance(message.media, MessageMediaPhoto) and downloaded_photos < download_photos:
                            file_name = await message.download_media(file=group_dir)

                            # Check if the media already exists, if so skip downloading
                            if os.path.exists(file_name):
                                logging.info(f"Media {file_name} already exists. Skipping download.")
                                continue

                            downloaded_photos += 1
                            logging.info(f"Downloaded photo to {file_name}")

                            # Post the photo to the target group
                            await post_media_to_group(client, target_group_input, file_name)

                        # Download videos if the user wants them
                        elif isinstance(message.media, MessageMediaDocument) and 'video' in message.media.document.mime_type and downloaded_videos < download_videos:
                            file_name = await message.download_media(file=group_dir)

                            # Check if the media already exists, if so skip downloading
                            if os.path.exists(file_name):
                                logging.info(f"Media {file_name} already exists. Skipping download.")
                                continue

                            downloaded_videos += 1
                            logging.info(f"Downloaded video to {file_name}")

                            # Post the video to the target group
                            await post_media_to_group(client, target_group_input, file_name)

                # Update offset_id to fetch older messages in the next iteration
                offset_id = messages[-1].id

            logging.info(f"Completed downloading and posting from group: {group.name}")

        except Exception as e:
            logging.error(f"Error harvesting media from group {group.name}: {e}")

async def main():
    """Main function to manage actions."""
    # Get credentials
    api_id = input("Enter your API ID: ").strip()
    api_hash = input("Enter your API Hash: ").strip()
    session_name = input("Enter a session name: ").strip()
    phone_number = input("Enter your phone number (with country code, e.g., +123456789): ").strip()

    # Initialize Telegram client
    async with TelegramClient(session_name, int(api_id), api_hash) as client:
        # Authenticate the client
        await authenticate(client, phone_number)

        # Harvest and post media from selected groups
        await harvest_and_post_media(client)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.error(f"Error running the script: {e}")
