# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import asyncio
import re
import html
from typing import Callable
from dataclasses import dataclass, field

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
    separator: str
    patterns: list[re.Pattern]
    fixup: Callable[[str], str] = None
    additions: list[str] = field(default_factory=list)
    rename_lock: asyncio.Lock = None
    revert_task: asyncio.Task = None


progtech_patterns = [
    re.compile(r"(?i)prog(?:ramming|gy) (?:&|and) (.+)"),
    re.compile(r"(?i)(.+) (?:is|are|and|&) te+chy?[.!]*$"),
]


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
    Group(
        1166076548,
        'Proggy & Techy for girls',
        separator=" & ",
        patterns=progtech_patterns,
        fixup=ptg_fixup,
    ),
    Group(
        1040270887,
        'Programming & Tech',
        separator=" & ",
        patterns=progtech_patterns,
        fixup=progtech_fixup,
    ),
    Group(
        1743238092,
        'Programming & Tech debug',
        separator=" & ",
        patterns=progtech_patterns,
        fixup=progtech_fixup,
    ),
    Group(
        1065200679,
        'kingdom of cute',
        separator=" and ",
        patterns=[
            re.compile(r"(?i)kingdom of (.+)"),
            re.compile(r"(?i)(.+) (?:is|are|and|&) cu+te+[.!]*$"),
        ],
        fixup=koc_fixup,
    ),
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


async def wait_and_revert(group):
    await asyncio.sleep(REVERT_TIMEOUT)
    async with group.rename_lock:
        await edit_title(group.id, group.title)
        group.additions = []


@borg.on(events.NewMessage)
async def _(event):
    event_gid = utils.get_peer_id(event.chat_id, False)  # Thanks Lonami
    group = GROUPS.get(event_gid)
    if group is not None:
        for p in group.patterns:
            if pattern_match := p.match(event.raw_text):
                await on_name(group, pattern_match, event)
                return


async def on_name(group, pattern_match, event):
    new_addition = pattern_match.group(1)
    additions = group.additions.copy()
    additions.append(new_addition)
    new_title = group.separator.join(additions)
    if callable(group.fixup):
        new_title = group.fixup(new_title)

    logger.info(f'{event.from_id} in {group.id} '
        f'requested a title change to {new_title}')

    if len(new_title) > 128:
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
        group.revert_task = asyncio.create_task(wait_and_revert(group))
        group.additions = additions

        logger.info(f'Holding rename lock for {MULTI_EDIT_TIMEOUT} seconds')
        await asyncio.sleep(MULTI_EDIT_TIMEOUT)


async def unload():
    for _, group in GROUPS.items():
        if group.revert_task and not group.revert_task.done():
            group.revert_task.cancel()


for _, group in GROUPS.items():
    asyncio.create_task(edit_title(group.id, group.title))
