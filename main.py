"""
HubSpot Todo メールスレッド確認・返信ツール

使い方:
  1. .env.example を .env にコピーして HUBSPOT_ACCESS_TOKEN を設定する
  2. pip install -r requirements.txt
  3. python main.py

機能:
  - 直近の未完了Todoタスクを一覧表示
  - タスクに紐づくコンタクトの直近メールスレッドを表示
  - スレッドへの返信メールを送信
"""

import os
import sys
import textwrap
from datetime import datetime, timezone, date
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv

from hubspot_client import HubSpotClient

load_dotenv()


# ------------------------------------------------------------------ #
# ヘルパー関数
# ------------------------------------------------------------------ #


def _ts(iso: Optional[str]) -> str:
    """ISO8601タイムスタンプを読みやすい日本語形式に変換する。"""
    if not iso:
        return "不明"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        local = dt.astimezone()
        return local.strftime("%Y/%m/%d %H:%M")
    except Exception:
        return iso


def _wrap(text: str, width: int = 80, indent: str = "  ") -> str:
    """長いテキストを折り返す。"""
    if not text:
        return ""
    return textwrap.fill(text, width=width, initial_indent=indent, subsequent_indent=indent)


def _sep(char: str = "-", width: int = 60) -> str:
    return char * width


def _input(prompt: str) -> str:
    return input(f"\n{prompt}> ").strip()


# ------------------------------------------------------------------ #
# 表示関数
# ------------------------------------------------------------------ #


def print_tasks(tasks: List[Dict]) -> None:
    print(f"\n{_sep('=')}")
    print(f"  直近のTodoタスク ({len(tasks)} 件)")
    print(_sep("="))
    for i, task in enumerate(tasks, 1):
        props = task.get("properties", {})
        subject = props.get("hs_task_subject") or "(件名なし)"
        status = props.get("hs_task_status") or ""
        priority = props.get("hs_task_priority") or ""
        ts = _ts(props.get("hs_timestamp"))
        print(f"\n[{i}] {subject}")
        print(f"     日時: {ts}  状態: {status}  優先度: {priority}")
        body = props.get("hs_task_body") or ""
        if body:
            print(_wrap(body[:200] + ("..." if len(body) > 200 else ""), indent="     "))


def print_threads(threads: List[Dict]) -> None:
    print(f"\n{_sep()}")
    print(f"  メールスレッド ({len(threads)} 件)")
    print(_sep())
    for i, thread in enumerate(threads, 1):
        thread_id = thread.get("id", "")
        subject = thread.get("subject") or "(件名なし)"
        status = thread.get("status") or ""
        updated = _ts(thread.get("updatedAt"))
        print(f"\n[{i}] ID: {thread_id}")
        print(f"     件名: {subject}")
        print(f"     状態: {status}  最終更新: {updated}")


def print_messages(messages: List[Dict]) -> None:
    print(f"\n{_sep()}")
    print("  メッセージ履歴 (新しい順)")
    print(_sep())
    for msg in messages:
        msg_id = msg.get("id", "")
        msg_type = msg.get("type", "")
        sender = msg.get("senderActorId", "")
        created = _ts(msg.get("createdAt"))
        text = msg.get("text") or ""
        print(f"\n  [{created}] type={msg_type}  sender={sender}  id={msg_id}")
        if text:
            print(_wrap(text[:400] + ("..." if len(text) > 400 else "")))


# ------------------------------------------------------------------ #
# フロー関数
# ------------------------------------------------------------------ #


def _today_start_ms() -> int:
    """今日の00:00:00 UTCをミリ秒で返す。"""
    today = date.today()
    dt = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def select_task(client: HubSpotClient, owner_id: Optional[str] = None) -> Optional[Dict]:
    """タスク一覧を表示して選択させる。"""
    print("\nTodoタスクを取得中...")
    from_ts = _today_start_ms()
    tasks = client.get_tasks(limit=20, status="NOT_STARTED", owner_id=owner_id, from_ts=from_ts)
    if not tasks:
        tasks = client.get_tasks(limit=20, owner_id=owner_id, from_ts=from_ts)
    if not tasks:
        print("タスクが見つかりませんでした。")
        return None

    print_tasks(tasks)
    choice = _input(f"タスク番号を選択 (1-{len(tasks)}, q=終了)")
    if choice.lower() == "q":
        return None
    try:
        idx = int(choice) - 1
        return tasks[idx]
    except (ValueError, IndexError):
        print("無効な番号です。")
        return None


def select_contact(client: HubSpotClient, task: Dict) -> Optional[Tuple[str, str]]:
    """タスクに紐づくコンタクトを取得して選択させる。"""
    task_id = task["id"]
    print(f"\nタスク {task_id} のコンタクトを取得中...")
    assocs = client.get_task_associations(task_id, "contacts")
    if not assocs:
        print("このタスクに紐づくコンタクトがありません。")
        return None

    contacts = []
    for assoc in assocs[:5]:
        cid = assoc.get("id") or assoc.get("toObjectId")
        if not cid:
            continue
        try:
            c = client.get_contact(str(cid))
            props = c.get("properties", {})
            name = f"{props.get('firstname','')} {props.get('lastname','')}".strip() or "(名前なし)"
            email = props.get("email") or ""
            contacts.append((str(cid), name, email))
        except Exception as e:
            print(f"  コンタクト {cid} の取得エラー: {e}")

    if not contacts:
        print("コンタクト情報を取得できませんでした。")
        return None

    print(f"\n{_sep()}")
    print("  紐づくコンタクト")
    print(_sep())
    for i, (cid, name, email) in enumerate(contacts, 1):
        print(f"  [{i}] {name} <{email}>  (ID: {cid})")

    if len(contacts) == 1:
        cid, name, email = contacts[0]
        print(f"\n  → コンタクト「{name}」を自動選択します。")
        return cid, name
    else:
        choice = _input(f"コンタクト番号を選択 (1-{len(contacts)})")
        try:
            idx = int(choice) - 1
            cid, name, _ = contacts[idx]
            return cid, name
        except (ValueError, IndexError):
            print("無効な番号です。")
            return None


def select_thread(client: HubSpotClient, contact_id: str) -> Optional[Dict]:
    """コンタクトのメールスレッド一覧を表示して選択させる。"""
    print(f"\nコンタクト {contact_id} のメールスレッドを取得中...")
    threads = client.get_threads_by_contact(contact_id, thread_status="OPEN", limit=5)
    if not threads:
        # OPENがなければCLOSEDも確認
        threads = client.get_threads_by_contact(contact_id, thread_status="CLOSED", limit=5)
    if not threads:
        print("メールスレッドが見つかりませんでした。")
        return None

    print_threads(threads)
    choice = _input(f"スレッド番号を選択 (1-{len(threads)}, q=戻る)")
    if choice.lower() == "q":
        return None
    try:
        idx = int(choice) - 1
        return threads[idx]
    except (ValueError, IndexError):
        print("無効な番号です。")
        return None


def show_messages_and_reply(client: HubSpotClient, thread: dict) -> None:
    """メッセージ履歴を表示して、返信するか確認する。"""
    thread_id = thread["id"]
    print(f"\nスレッド {thread_id} のメッセージを取得中...")
    messages = client.get_thread_messages(thread_id, limit=10)
    if not messages:
        print("メッセージが見つかりませんでした。")
        return

    print_messages(messages)

    # 最新メッセージから送信者情報・チャンネル情報を取得
    latest = messages[0]
    sender_actor_id = latest.get("senderActorId", "")
    channel_id = str(latest.get("channelId") or "")
    channel_account_id = str(latest.get("channelAccountId") or "")

    # 返信先: 最新メッセージの送信者にTO返信
    recipients_from_msg = latest.get("recipients", [])

    print(f"\n{_sep()}")
    choice = _input("このスレッドに返信しますか? (y/n)")
    if choice.lower() != "y":
        print("返信をキャンセルしました。")
        return

    # 返信内容の入力
    print("\n返信本文を入力してください (入力完了: 空行で終了):")
    lines = []
    while True:
        line = input()
        if line == "":
            break
        lines.append(line)
    reply_text = "\n".join(lines).strip()
    if not reply_text:
        print("本文が空のため返信をキャンセルしました。")
        return

    # 受信者の設定
    # スレッド内の相手(送信者)にTOで返信する
    if recipients_from_msg:
        # 既存受信者をそのまま利用
        reply_recipients = [
            {**r, "recipientField": "TO"}
            for r in recipients_from_msg
            if r.get("recipientField") != "FROM"
        ]
    else:
        # フォールバック: 手動入力
        to_email = _input("返信先メールアドレスを入力")
        to_name = _input("返信先名前を入力 (省略可)")
        reply_recipients = [
            {
                "recipientField": "TO",
                "deliveryIdentifiers": [
                    {"type": "HS_EMAIL_ADDRESS", "value": to_email}
                ],
            }
        ]
        if to_name:
            reply_recipients[0]["name"] = to_name

    subject = thread.get("subject") or ""
    if subject and not subject.startswith("Re:"):
        subject = f"Re: {subject}"

    print("\n送信中...")
    try:
        result = client.reply_to_thread(
            thread_id=thread_id,
            text=reply_text,
            sender_actor_id=sender_actor_id,
            channel_id=channel_id,
            channel_account_id=channel_account_id,
            recipients=reply_recipients,
            subject=subject or None,
        )
        msg_id = result.get("id", "")
        print(f"\n返信を送信しました! (メッセージID: {msg_id})")
    except Exception as e:
        print(f"\n送信エラー: {e}")


# ------------------------------------------------------------------ #
# メイン
# ------------------------------------------------------------------ #


def main() -> None:
    token = os.getenv("HUBSPOT_ACCESS_TOKEN")
    if not token:
        print("エラー: HUBSPOT_ACCESS_TOKEN が設定されていません。")
        print("  .env.example を .env にコピーしてトークンを設定してください。")
        sys.exit(1)

    owner_id = os.getenv("HUBSPOT_OWNER_ID") or None
    client = HubSpotClient(token)

    print(_sep("="))
    print("  HubSpot Todo メールスレッド 確認・返信ツール")
    print(_sep("="))
    if owner_id:
        print(f"  フィルター: 自分 (OwnerID: {owner_id}) / 今日以降のタスク")
    else:
        print("  フィルター: 今日以降のタスク (HUBSPOT_OWNER_ID 未設定のため担当者フィルターなし)")

    while True:
        # 1. タスク選択
        task = select_task(client, owner_id=owner_id)
        if task is None:
            print("\n終了します。")
            break

        # 2. コンタクト選択
        result = select_contact(client, task)
        if result is None:
            continue
        contact_id, contact_name = result
        print(f"\n選択したコンタクト: {contact_name} (ID: {contact_id})")

        # 3. スレッド選択
        thread = select_thread(client, contact_id)
        if thread is None:
            continue

        # 4. メッセージ表示・返信
        show_messages_and_reply(client, thread)

        # 続けるか確認
        again = _input("\n別のタスクを確認しますか? (y/n)")
        if again.lower() != "y":
            print("\n終了します。")
            break


if __name__ == "__main__":
    main()
