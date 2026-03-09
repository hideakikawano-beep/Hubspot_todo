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


def print_emails(emails: List[Dict]) -> None:
    print(f"\n{_sep()}")
    print(f"  メール履歴 ({len(emails)} 件、新しい順)")
    print(_sep())
    for i, email in enumerate(emails, 1):
        props = email.get("properties", {})
        subject = props.get("hs_email_subject") or "(件名なし)"
        direction = props.get("hs_email_direction") or ""
        from_email = props.get("hs_email_from_email") or ""
        to_email = props.get("hs_email_to_email") or ""
        ts = _ts(props.get("hs_timestamp"))
        arrow = "→" if "OUTGOING" in direction else "←"
        print(f"\n[{i}] {arrow} {subject}")
        print(f"     日時: {ts}")
        print(f"     From: {from_email}  To: {to_email}")
        body = props.get("hs_email_text") or ""
        if body:
            print(_wrap(body[:300] + ("..." if len(body) > 300 else ""), indent="     "))


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


def show_emails_and_log_reply(
    client: HubSpotClient,
    contact_id: str,
    contact_name: str,
    owner_id: Optional[str],
) -> None:
    """メール履歴を表示して、返信をHubSpotに記録する。"""
    print(f"\nコンタクト {contact_id} のメール履歴を取得中...")
    emails = client.get_contact_emails(contact_id, limit=10)
    if not emails:
        print("メール履歴が見つかりませんでした。")
        return

    print_emails(emails)

    print(f"\n{_sep()}")
    choice = _input("このコンタクトへの返信をHubSpotに記録しますか? (y/n)")
    if choice.lower() != "y":
        print("記録をキャンセルしました。")
        return

    # 最新メールから件名・返信先アドレスを推定
    latest_props = emails[0].get("properties", {})
    latest_subject = latest_props.get("hs_email_subject") or ""
    default_to = latest_props.get("hs_email_from_email") or ""
    direction = latest_props.get("hs_email_direction") or ""
    # 自分が送ったメールなら to_email が相手
    if "OUTGOING" in direction:
        default_to = latest_props.get("hs_email_to_email") or default_to

    from_email = _input("自分のメールアドレス (Fromに使用)")
    to_email_input = _input(f"返信先アドレス (Enter でそのまま: {default_to})")
    to_email = to_email_input if to_email_input else default_to

    subject = latest_subject
    if subject and not subject.startswith("Re:"):
        subject = f"Re: {subject}"
    subject_input = _input(f"件名 (Enter でそのまま: {subject})")
    if subject_input:
        subject = subject_input

    print("\n返信本文を入力してください (空行で終了):")
    lines = []
    while True:
        line = input()
        if line == "":
            break
        lines.append(line)
    reply_text = "\n".join(lines).strip()
    if not reply_text:
        print("本文が空のため記録をキャンセルしました。")
        return

    print("\nHubSpotに記録中...")
    try:
        result = client.log_email(
            contact_id=contact_id,
            from_email=from_email,
            to_email=to_email,
            subject=subject,
            text=reply_text,
            owner_id=owner_id,
        )
        email_id = result.get("id", "")
        print(f"\nHubSpotに記録しました! (メールID: {email_id})")
        print("※ 実際の送信はGmailから行ってください。")
    except Exception as e:
        print(f"\n記録エラー: {e}")


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

        # 3. メール履歴表示・返信記録
        show_emails_and_log_reply(client, contact_id, contact_name, owner_id)

        # 続けるか確認
        again = _input("\n別のタスクを確認しますか? (y/n)")
        if again.lower() != "y":
            print("\n終了します。")
            break


if __name__ == "__main__":
    main()
