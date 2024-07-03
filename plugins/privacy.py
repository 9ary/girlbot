# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Query privacy policy
"""

@borg.on(borg.cmd("privacy"))
async def _(e):
    await e.respond("This bot does not collect any user data")
