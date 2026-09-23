"""Confirm notebook listing, note read, and a conditional text update.

Creates one note titled "EverStickyNote API確認" in the first notebook,
updates it, then checks that a stale USN does not overwrite it.
A token is read from EVERNOTE_DEV_TOKEN or the local app settings.
"""

from __future__ import annotations

import os
import sys

from evernote_client import EvernoteClient, EvernoteError
from local_store import LocalStore
from sync import enml_to_text, text_to_enml

SPIKE_TITLE = "EverStickyNote API確認"


def resolve_token() -> str:
    env_token = os.environ.get("EVERNOTE_DEV_TOKEN", "").strip()
    if env_token:
        return env_token
    return LocalStore().get_token().strip()


def run_spike(client: EvernoteClient) -> str:
    notebooks = client.list_notebooks()
    if not notebooks:
        raise EvernoteError("ノートブックがありません")
    notebook = notebooks[0]
    created = client.create_note(notebook.guid, SPIKE_TITLE, text_to_enml("確認1"))
    fetched = client.get_note(created.guid)
    if enml_to_text(fetched.content) != "確認1":
        raise EvernoteError("取得した本文が一致しません")
    updated = client.update_note_if_usn_matches(
        fetched.guid,
        fetched.title,
        text_to_enml("確認2"),
        fetched.update_sequence_num,
    )
    if not updated.updated:
        raise EvernoteError("条件付き更新が拒否されました")
    again = client.get_note(created.guid)
    if enml_to_text(again.content) != "確認2":
        raise EvernoteError("更新後の本文が一致しません")
    stale = client.update_note_if_usn_matches(
        again.guid,
        again.title,
        text_to_enml("確認3"),
        fetched.update_sequence_num,
    )
    if stale.updated:
        raise EvernoteError("古いUSNで上書きできてしまいました")
    if enml_to_text(stale.note.content) != "確認2":
        raise EvernoteError("衝突後の本文がサーバの内容ではありません")
    return (
        f"notebooks={len(notebooks)} notebook={notebook.name} "
        f"note={created.guid} read_ok update_ok conflict_ok"
    )


def main() -> int:
    token = resolve_token()
    if not token:
        print(
            "トークンが未設定です。アプリの接続欄に開発者トークンを入れるか、"
            "環境変数 EVERNOTE_DEV_TOKEN を設定してから python spike_api.py を実行してください。",
            file=sys.stderr,
        )
        return 2
    try:
        client = EvernoteClient(token)
        client.connect()
        print(run_spike(client))
    except Exception as exc:
        from evernote_client import format_evernote_error

        print(format_evernote_error(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
