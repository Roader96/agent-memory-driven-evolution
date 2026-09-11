#!/usr/bin/env python3
"""Feishu proactive DM — 适配 cron 场景"""
import os
import sys
import json
import requests
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple

ENV_FILE = Path.home() / ".hermes" / ".env"
CHANNEL_DIR = Path.home() / ".hermes" / "channel_directory.json"
LOG_FILE = Path.home() / ".hermes" / "logs" / "cron_failures.log"


def load_feishu_creds() -> Tuple:
    env = {}
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k] = v
    return env["FEISHU_APP_ID"], env["FEISHU_APP_SECRET"]


def load_dm_chat_id() -> Optional[str]:
    if not CHANNEL_DIR.exists():
        return None
    d = json.loads(CHANNEL_DIR.read_text())
    for entry in d.get("platforms", {}).get("feishu", []):
        if entry.get("type") == "dm":
            return entry["id"]
    return None


def get_token(app_id: str, app_secret: str) -> str:
    assert len(app_secret) == 32, f"FEISHU_APP_SECRET length is {len(app_secret)}, expected 32"
    r = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    assert data.get("code") == 0, f"token api error: {data}"
    return data["tenant_access_token"]


def send_dm(text: str) -> bool:
    try:
        app_id, app_secret = load_feishu_creds()
        chat_id = load_dm_chat_id()
        if not chat_id:
            raise RuntimeError("no DM chat_id found in channel_directory.json")
        token = get_token(app_id, app_secret)
        resp = requests.post(
            "https://open.feishu.cn/open-apis/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "receive_id": chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}),
            },
            timeout=15,
        )
        data = resp.json()
        if data.get("code") == 0:
            print(f"[OK] feishu DM sent to {chat_id}")
            print(f"[OK] message_id: {data['data']['message_id']}")
            return True
        raise RuntimeError(f"feishu returned code={data.get('code')}: {data.get('msg')}")
    except Exception as e:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] feishu DM cron failed: {e}\n")
        print(f"[FAIL] {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    msg = sys.argv[1] if len(sys.argv) > 1 else "[cron] hello"
    sys.exit(0 if send_dm(msg) else 1)
