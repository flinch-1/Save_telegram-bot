import json
import os
import logging
import asyncio
from telethon import TelegramClient
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

# Configure logging
logging.basicConfig(level=logging.WARNING, format="%(asctime)s - %(levelname)s - %(message)s")
logging.getLogger("telethon").setLevel(logging.DEBUG)

# File to store credentials
CREDENTIALS_FILE = "credentials.json"


def save_credentials(api_id, api_hash, session_name, phone_number=None):
    """Save API credentials and phone number to a file."""
    with open(CREDENTIALS_FILE, "w") as f:
        json.dump(
            {"API_ID": api_id, "API_HASH": api_hash, "SESSION_NAME": session_name, "PHONE_NUMBER": phone_number}, f
        )
    logging.info("Credentials saved successfully!")


def load_credentials():
    """Load API credentials from a file."""
    if os.path.exists(CREDENTIALS_FILE):
        with open(CREDENTIALS_FILE, "r") as f:
            return json.load(f)
    return None


def get_credentials():
    """Get credentials from the user or reuse saved credentials."""
    saved_credentials = load_credentials()
    if saved_credentials:
        use_saved = input("Saved credentials found. Do you want to use them? (yes/no): ").strip().lower()
        if use_saved == "yes":
            return (
                saved_credentials["API_ID"],
                saved_credentials["API_HASH"],
                saved_credentials["SESSION_NAME"],
                saved_credentials.get("PHONE_NUMBER"),
            )

    # Prompt for new credentials
    api_id = input("Enter your API ID: ").strip()
    api_hash = input("Enter your API Hash: ").strip()
    session_name = input("Enter a session name: ").strip()
    phone_number = input("Enter your phone number (with country code, e.g., +123456789): ").strip()

    # Ask if the user wants to save these credentials
    save = input("Do you want to save these credentials for future use? (yes/no): ").strip().lower()
    if save == "yes":
        save_credentials(api_id, api_hash, session_name, phone_number)

    return api_id, api_hash, session_name, phone_number


async def authenticate(client, phone_number):
    """Authenticate the user and connect the client."""
    if not client.is_connected():
        await client.connect()

    if not await client.is_user_authorized():
        logging.info("Client not authorized. Sending code...")
        await client.start(phone=phone_number)
        logging.info("Authorization complete!")


async def join_groups(client):
    """Join Telegram groups using invite links or usernames."""
    group_input = input("Enter the group invite links or usernames (comma-separated): ").split(",")
    group_input = [item.strip() for item in group_input]

    for item in group_input:
        try:
            # If the input starts with '@', it's a username, otherwise, it's an invite link
            if item.startswith('@'):
                await client(JoinChannelRequest(item))
                logging.info(f"Successfully joined group (username): {item}")
            else:
                await client(JoinChannelRequest(item))
                logging.info(f"Successfully joined group (invite link): {item}")
        except Exception as e:
            logging.error(f"Failed to join group {item}: {e}")


async def download_and_post_media(client, group_dir, target_group_input, messages, downloaded_photos, downloaded_videos, download_photos, download_videos):
    """Download media concurrently and post it to the target group."""
    semaphore = asyncio.Semaphore(5)  # Limit to 5 concurrent downloads
    tasks = []  # List of tasks to run concurrently
    max_video_duration = 10 * 60  # 10 minutes in seconds

    async def download_and_post(message):
        """Download a single message's media and post it."""
        nonlocal downloaded_photos, downloaded_videos
        async with semaphore:
            if message.media:
                # Handle photos
                if isinstance(message.media, MessageMediaPhoto) and downloaded_photos < download_photos:
                    file_name = await message.download_media(file=group_dir)
                    if file_name and not os.path.exists(file_name):
                        downloaded_photos += 1
                        logging.info(f"Downloaded photo to {file_name}")
                        await post_media_to_group(client, target_group_input, file_name)

                # Handle videos
                elif (
                    isinstance(message.media, MessageMediaDocument)
                    and "video" in message.media.document.mime_type
                    and downloaded_videos < download_videos
                ):
                    # Check video duration from attributes
                    for attr in message.media.document.attributes:
                        if hasattr(attr, "duration") and attr.duration > max_video_duration:
                            logging.warning(f"Skipped video longer than 10 minutes: {attr.duration} seconds")
                            return  # Skip this video

                    file_name = await message.download_media(file=group_dir)
                    if file_name and not os.path.exists(file_name):
                        downloaded_videos += 1
                        logging.info(f"Downloaded video to {file_name}")
                        await post_media_to_group(client, target_group_input, file_name)

    # Create tasks for each message with media
    for message in messages:
        tasks.append(download_and_post(message))

    # Run all tasks concurrently
    await asyncio.gather(*tasks)


async def harvest_and_post_media(client):
    """Harvest media from selected groups and post to the target group."""
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

    # Get the target group where media will be posted
    target_group_input = input("Enter the username or invite link of the target group where media will be posted: ").strip()

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

            # Second pass: Download the selected number of photos and videos and post to target group
            downloaded_photos = 0
            downloaded_videos = 0
            offset_id = 0  # Reset the offset_id to start from the latest message again

            while True:
                messages = await client.get_messages(group.id, offset_id=offset_id, limit=limit)
                if not messages:
                    break  # No more messages to fetch

                await download_and_post_media(client, group_dir, target_group_input, messages, downloaded_photos, downloaded_videos, download_photos, download_videos)

                # Update offset_id to fetch older messages in the next iteration
                offset_id = messages[-1].id

            logging.info(f"Completed downloading and posting media from group: {group.name}")

        except Exception as e:
            logging.error(f"Error harvesting media from group {group.name}: {e}")


async def main():
    """Main function to manage actions."""
    # Get credentials
    api_id, api_hash, session_name, phone_number = get_credentials()

    # Initialize Telegram client
    async with TelegramClient(session_name, int(api_id), api_hash) as client:
        # Authenticate the client
        await authenticate(client, phone_number)

        # Prompt user for actions
        join_choice = input("Do you want to join groups? (yes/no): ").strip().lower()
        if join_choice == "yes":
            await join_groups(client)

        harvest_choice = input("Do you want to harvest media from groups? (yes/no): ").strip().lower()
        if harvest_choice == "yes":
            await harvest_and_post_media(client)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.error(f"Error running the script: {e}")
