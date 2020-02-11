# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import asyncio
import re
import html
from dataclasses import dataclass
import os
import logging

from telethon import TelegramClient, events, utils
from telethon.tl.functions.channels import EditTitleRequest
from telethon.errors.rpcerrorlist import ChatNotModifiedError


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("girlbot")

client = TelegramClient(
    "girlbot",
    api_id=6,
    api_hash="eb06d4abfb49dc3eeb1aeb98ae0f581e"
)


MULTI_EDIT_TIMEOUT = 80
REVERT_TIMEOUT = 2 * 60 * 60


@dataclass
class Group:
    id: int
    title: str
    rename_lock = asyncio.Lock()
    revert_task: asyncio.Task = None


GROUPS = {group.id: group for group in (
    Group(1384391544, 'Programming & Tech for girls'),
)}


def fix_title(s):
    # Ideally this would be a state machine, but ¯\_(ツ)_/¯
    def replace(m):
        token = m.group(1)
        if token.lower() == 'and':
            token = '&'
        return token[0].upper() + token[1:] + (' ' if m.group(2) else '')
    return re.sub(r'(\S+)(\s+)?', replace, s)


async def edit_title(chat, title):
    try:
        await client(EditTitleRequest(
            channel=chat, title=title
        ))
    except ChatNotModifiedError:
        pass  # Everything is ok


async def wait_and_revert(chat_id, title, timeout):
    await asyncio.sleep(timeout)
    await edit_title(chat_id, title)


@client.on(events.NewMessage(
    pattern=re.compile(r"(?i)programming (?:&|and) (.+)"),
    chats=list(GROUPS.keys())))
async def on_name(event):
    new_topic = fix_title(event.pattern_match.group(1))
    new_title = f"Programming & {new_topic}"
    if "tech" not in new_title.lower():
        new_title += " & Tech"
    if "girl" not in new_title.lower():
        new_title += " for girls"

    group = GROUPS[utils.get_peer_id(event.chat_id, False)]  # Thanks Lonami

    logger.info(f'{event.from_id} in {group.id} '
        f'requested a title change to {new_title}')

    if len(new_title) > 255:
        logger.info('Not changing group title because new title is too long')
        return

    if group.rename_lock.locked():
        logger.info('Not changing group title because the rename lock is already held')
        return

    with (await group.rename_lock):
        if group.revert_task and not group.revert_task.done():
            logger.info('Cancelling previous revert task')
            group.revert_task.cancel()

        logger.info(f'Changing group title to {new_title}')
        await event.respond(
            f'<a href="tg://user?id={event.from_id}">{html.escape(event.sender.first_name)}</a>'
            ' changed the group title!',
            parse_mode='html'
        )
        await edit_title(event.chat_id, new_title)

        logger.info('Creating revert task')
        group.revert_task = asyncio.create_task(wait_and_revert(
            event.chat_id,
            group.title,
            REVERT_TIMEOUT
        ))

        logger.info(f'Holding rename lock for {MULTI_EDIT_TIMEOUT} seconds')
        await asyncio.sleep(MULTI_EDIT_TIMEOUT)

client.start()
client.run_until_disconnected()
