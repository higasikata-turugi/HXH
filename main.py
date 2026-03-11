import os
from dotenv import load_dotenv
import sys
import time
import re
import smtplib
from urllib.parse import urlparse, parse_qs
from email.message import EmailMessage

import feedparser
import gspread
import google.auth
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
import traceback
import socket

load_dotenv()

# --- 設定（環境変数から読み込む） ---
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GMAIL_USER = os.environ["GMAIL_USER"]
APP_PASSWORD = os.environ["APP_PASSWORD"]
TO_EMAIL = os.environ["TO_EMAIL"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]

# GoogleアラートのRSSフィードURL
RESUME_RSS_URL = (
    "https://www.google.com/alerts/feeds/16346842236686014180/15858924254145587718"
)
HIATUS_RSS_URL = (
    "https://www.google.com/alerts/feeds/16346842236686014180/8471829281408147332"
)

# --- 初期化 ---
genai.configure(api_key=GEMINI_API_KEY)


def get_sheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    credentials, _ = google.auth.default(scopes=scopes)
    gc = gspread.authorize(credentials)
    return gc.open_by_key(SPREADSHEET_ID).get_worksheet(0)


def extract_actual_url(google_alert_url):
    """GoogleアラートのリダイレクトURLから実際のニュースURLを抽出する"""
    parsed = urlparse(google_alert_url)
    if parsed.netloc == "www.google.com" and parsed.path == "/url":
        qs = parse_qs(parsed.query)
        # 'url' パラメータ（または 'q'）が存在すればそれを返す
        if "url" in qs:
            return qs["url"][0]
        elif "q" in qs:
            return qs["q"][0]
    return google_alert_url


def get_latest_news(rss_url):
    socket.setdefaulttimeout(10)
    print("RSSフィードを取得中...")
    try:
        feed = feedparser.parse(rss_url)
        print(f"フィード取得完了: {len(feed.entries)} 件のニュースが見つかりました")
    except Exception as e:
        print(f"RSS取得でエラーが発生しました: {e}")
    return [
        {
            "title": entry.title,
            "link": extract_actual_url(entry.link),
            "summary": entry.summary,
        }
        for entry in feed.entries
    ]


def validate_and_generate_email(news_title, news_summary, mode):
    """Geminiによる審査と生成。複数モデルによるフォールバック機構付き"""

    if mode == "resume":
        target_word = "連載再開"
        extra_instruction = "- 腰痛の具合や原稿の進捗、ゲームの話などを適度に交える。"
    else:
        target_word = "休載"
        extra_instruction = "- 腰痛が限界に達していることや、執筆環境の厳しさなどを交えて休載の言い訳をする。"

    prompt = f"""
    以下のニュース記事のタイトルと概要を読み、漫画『HUNTER×HUNTER』の{target_word}が「公式に確定した」という事実を報じているか判定してください。

    【ニュースタイトル】: {news_title}
    【概要】: {news_summary}

    【厳格なルール】
    噂、ネットの予想、考察、過去の話題、または{target_word}が確定していない内容である場合は、絶対にメールを作成せず、半角大文字で「NO」という2文字だけを出力してください。

    【確定情報である場合のみ】
    公式発表に基づく確実な{target_word}のニュースであると判断した場合のみ、以下の指示に従って冨樫義博先生がファンに直接送ってきたようなメールを作成してください。
    - 宛名は「読者のみんなへ」などで始める。
    {extra_instruction}
    - 媚びすぎず、淡々としつつも漫画への熱意が伝わる特有のトーンにする。
    - 最後に「冨樫義博」と署名を入れる。
    """

    models_to_try = [
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
        "gemini-3.1-flash-lite-preview",
    ]

    for model_name in models_to_try:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(
                prompt, generation_config={"temperature": 0.2}
            )
            return response.text.strip()

        except google_exceptions.ResourceExhausted as e:
            print(
                f"警告: {model_name} のリクエスト制限に達しました。次のモデルを試します... ({e})"
            )
            continue
        except Exception as e:
            print(
                f"警告: {model_name} で予期せぬエラーが発生しました。次のモデルを試します... ({e})"
            )
            continue

    print("致命的なエラー: 全てのモデルで生成に失敗しました。")
    return "NO"


def send_email(subject, body, news_link):
    full_body = f"{body}\n\n---\n情報ソース: {news_link}"

    # モダンなEmailMessageクラスを使用
    msg = EmailMessage()
    msg.set_content(full_body)
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = TO_EMAIL

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, APP_PASSWORD)
        server.send_message(msg)


def append_urls_to_column(sheet, col_index, urls):
    """指定した列(1=A列, 2=B列)の最下部にURLリストを追記する"""
    if not urls:
        return
    existing_values = sheet.col_values(col_index)
    next_row = len(existing_values) + 1
    col_letter = "A" if col_index == 1 else "B"

    values_to_update = [[url] for url in urls]
    range_name = f"{col_letter}{next_row}:{col_letter}{next_row + len(urls) - 1}"

    # gspread v6.0.0以降の仕様に合わせてキーワード引数を使用
    sheet.update(values=values_to_update, range_name=range_name)


# --- 実行ブロック ---
if __name__ == "__main__":
    try:
        print("プログラムを開始しました...")
        sheet = get_sheet()

        current_status = sheet.acell("C1").value
        if current_status not in ["連載中", "休載中"]:
            current_status = "休載中"
            sheet.update_acell("C1", current_status)
            print("C1セルの状態が不明なため、「休載中」に初期化しました。")

        if current_status == "休載中":
            print("現在のステータス: 休載中 (連載再開を監視します)")
            target_rss_url = RESUME_RSS_URL
            history_col_index = 1
            mode = "resume"
            subject = "【送信元: 冨樫義博】連載再開のお知らせ"
            next_status = "連載中"
        else:
            print("現在のステータス: 連載中 (休載を監視します)")
            target_rss_url = HIATUS_RSS_URL
            history_col_index = 2
            mode = "hiatus"
            subject = "【送信元: 冨樫義博】休載のお知らせ"
            next_status = "休載中"

        sent_urls = set(sheet.col_values(history_col_index))
        news_items = get_latest_news(target_rss_url)

        if not news_items:
            print("新しいアラートはありません。")
            sys.exit()

        new_urls_to_record = []

        for news in news_items:
            if news["link"] in sent_urls:
                continue

            time.sleep(2)

            result_text = validate_and_generate_email(
                news["title"], news["summary"], mode
            )

            cleaned_text = result_text.strip().upper()
            is_short_no = len(cleaned_text) <= 50 and "NO" in cleaned_text
            is_regex_no = bool(re.search(r"(?<![A-Z])NO(?![A-Z])", cleaned_text))
            has_signature = "冨樫義博" in result_text

            if is_short_no or is_regex_no or not has_signature:
                preview = result_text[:30].replace("\n", " ")
                print(
                    f"スキップ: 確定情報ではない、または要件未達 [出力プレビュー: {preview}...]"
                )
                new_urls_to_record.append(news["link"])
                continue

            print(f"確定情報と判定されました。{mode}のメールを送信します。")

            try:
                send_email(subject, result_text, news["link"])
            except Exception as e:
                print(f"メール送信中にエラーが発生しました。処理を中断します: {e}")
                break

            sheet.update_acell("C1", next_status)
            print(f"メール送信完了！C1セルを「{next_status}」に変更しました。")

            new_urls_to_record.append(news["link"])
            break

        if new_urls_to_record:
            append_urls_to_column(sheet, history_col_index, new_urls_to_record)
            print(
                f"{len(new_urls_to_record)}件のURLをスプレッドシートの{history_col_index}列目に記録しました。"
            )

    except Exception as e:
        print(f"全体処理で致命的なエラー発生: {e}")
        traceback.print_exc()
