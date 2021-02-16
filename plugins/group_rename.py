# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import asyncio
import re
import html
from typing import Callable
from dataclasses import dataclass

from telethon import TelegramClient, events, utils
from telethon.tl.functions.channels import EditTitleRequest
from telethon.errors.rpcerrorlist import ChatNotModifiedError
from telethon.errors.rpcerrorlist import ChatAdminRequiredError


MULTI_EDIT_TIMEOUT = 80
REVERT_TIMEOUT = 2 * 60 * 60


@dataclass
class Group:
    id: int
    title: str
    regex: re.Pattern
    fixup: Callable[[str], str] = None
    rename_lock: asyncio.Lock = None
    revert_task: asyncio.Task = None


progtech_regex = re.compile(r"(?i)prog(?:ramming|gy) (?:&|and) (.+)")


def ptg_fixup(new_title):
    new_title = f"Proggy & {fix_title(new_title)}"
    if "tech" not in new_title.lower():
        new_title += " & Techy"
    if "girl" not in new_title.lower():
        new_title += " for girls"
    return new_title


def progtech_fixup(new_title):
    new_title = f"Programming & {fix_title(new_title)}"
    if "tech" not in new_title.lower():
        new_title += " & Tech"
    return new_title


def koc_fixup(new_title):
    new_title = f"kingdom of {new_title}"
    if "cute" not in new_title.lower():
        new_title += " and cute"
    return new_title


GROUPS = {group.id: group for group in (
    Group(1166076548, 'Proggy & Techy for girls',
        regex=progtech_regex, fixup=ptg_fixup),
    Group(1040270887, 'Programming & Tech',
        regex=progtech_regex, fixup=progtech_fixup),
    Group(1065200679, 'kingdom of cute',
        regex=re.compile(r"(?i)kingdom of (.+)"), fixup=koc_fixup),
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
        await borg(EditTitleRequest(
            channel=chat, title=title
        ))
    except ChatNotModifiedError:
        pass  # Everything is ok


async def wait_and_revert(chat_id, title, timeout):
    await asyncio.sleep(timeout)
    await edit_title(chat_id, title)


async def on_name(event):
    group = GROUPS[utils.get_peer_id(event.chat_id, False)]  # Thanks Lonami

    new_title = event.pattern_match.group(1)
    if callable(group.fixup):
        new_title = group.fixup(new_title)

    logger.info(f'{event.from_id} in {group.id} '
        f'requested a title change to {new_title}')

    if len(new_title) > 255:
        logger.info('Not changing group title because new title is too long')
        return

    if group.rename_lock is None:
        group.rename_lock = asyncio.Lock()

    if group.rename_lock.locked():
        logger.info('Not changing group title because the rename lock is already held')
        return

    async with group.rename_lock:
        if group.revert_task and not group.revert_task.done():
            logger.info('Cancelling previous revert task')
            group.revert_task.cancel()

        logger.info(f'Changing group title to {new_title}')
        await event.respond(
            f'<a href="tg://user?id={event.from_id}">{html.escape(event.sender.first_name)}</a>'
            ' changed the group title!',
            parse_mode='html'
        )
        try:
            await edit_title(event.chat_id, new_title)
        except ChatAdminRequiredError:
            logger.warn("Can't change group title due to missing permission")
            await event.respond('Need admin rights to change group info!')
            return

        logger.info('Creating revert task')
        group.revert_task = asyncio.create_task(wait_and_revert(
            event.chat_id,
            group.title,
            REVERT_TIMEOUT
        ))

        logger.info(f'Holding rename lock for {MULTI_EDIT_TIMEOUT} seconds')
        await asyncio.sleep(MULTI_EDIT_TIMEOUT)


async def unload():
    for _, group in GROUPS.items():
        if group.revert_task and not group.revert_task.done():
            group.revert_task.cancel()


for _, group in GROUPS.items():
    borg.add_event_handler(on_name,
        events.NewMessage(pattern=group.regex, chats=[group.id]))
    asyncio.create_task(edit_title(group.id, group.title))
