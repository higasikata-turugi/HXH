# HxH Status Monitor

## 概要
『HUNTER×HUNTER』の連載再開および休載情報をGoogleアラートのRSSフィードから自動取得し、Gemini APIを用いて公式の確定情報であるかを判定・文面生成した上で、メールで通知するシステムです。
GitHub Actionsを利用して1時間ごとに自動実行され、Google Workspace（スプレッドシート）へのアクセスにはWorkload Identity Federation (WIF) を使用しています。

## 特徴
- **RSSフィード監視**: GoogleアラートのRSSから最新ニュースを取得。リダイレクトURLから実際のニュースURLを抽出。
- **AIによる真偽判定と文章生成**: Gemini APIを活用し、噂や考察を弾き、公式発表のみを抽出。冨樫義博先生本人からのメッセージのような文面を自動生成。複数モデルのフォールバック機構を搭載。
- **状態管理**: Googleスプレッドシートを使用して現在のステータス（「連載中」または「休載中」）と通知済みURLを永続化。
- **セキュアな自動実行**: GitHub Actionsによる定期実行（毎時0分）と、WIFによる認証キーを持たない安全なGoogle API連携。

## 前提条件・必要なもの
- Google アカウント (Gmail送信用、スプレッドシート用、Google Cloud Console用)
- Gemini API キー
- GitHub アカウントおよびリポジトリ
- Python 3.11 以上 (ローカルで実行する場合)

## スプレッドシートの準備
1. 新規スプレッドシートを作成し、IDを取得します。（URLの `d/` と `/edit` の間の文字列）
2. 1つ目のシート（インデックス0）を使用します。
3. 初期状態として、**C1セル**に `休載中` または `連載中` と入力してください。（未入力の場合は初回実行時に `休載中` で初期化されます）
4. A列には連載再開ニュースのURL、B列には休載ニュースのURLが自動で記録されていきます。

## 環境変数 / GitHub Secrets の設定

ローカル環境（`.env` ファイル）および GitHubリポジトリの **Settings > Secrets and variables > Actions** に以下の変数を設定してください。

### アプリケーション設定
| 変数名 | 説明 |
|---|---|
| `GEMINI_API_KEY` | Google AI Studio で発行したAPIキー |
| `GMAIL_USER` | 送信元となるGmailアドレス |
| `APP_PASSWORD` | 上記Gmailアカウントのアプリパスワード（2段階認証を有効にして発行） |
| `TO_EMAIL` | 通知を受け取る宛先のメールアドレス |
| `SPREADSHEET_ID` | 用意したスプレッドシートのID |

### GitHub Actions (WIF) 用設定
Google CloudでWorkload Identity Federationを設定し、スプレッドシートへのアクセス権限（Google Sheets API, Google Drive API）を持つサービスアカウントを紐付けます。該当のサービスアカウントには、作成したスプレッドシートに対する「編集者」権限を共有設定で付与してください。

| 変数名 | 説明 |
|---|---|
| `WIF_PROVIDER` | WIFのプロバイダ名（例: `projects/123456789/locations/global/workloadIdentityPools/my-pool/providers/my-provider`） |
| `WIF_SERVICE_ACCOUNT` | 紐付けたサービスアカウントのメールアドレス |

## ローカル環境での実行方法

1. リポジトリをクローンし、依存パッケージをインストールします。
   ```bash
   pip install feedparser gspread google-auth google-generativeai python-dotenv
   ```
2. プロジェクトルートに `.env` ファイルを作成し、必要な環境変数を記述します。
   （ローカル実行時は、Google Application Default Credentials (ADC) を使用するため、事前に `gcloud auth application-default login` で認証を済ませるか、サービスアカウントキーのJSONを `GOOGLE_APPLICATION_CREDENTIALS` として指定してください。）
3. スクリプトを実行します。
   ```bash
   python main.py
   ```

## 動作フロー
1. スプレッドシートのC1セルを確認し、現在のステータス（休載中/連載中）を判定。
2. 現在のステータスに応じたGoogleアラートRSSフィード（再開/休載）を取得。
3. 新着記事（スプレッドシートに未記録のURL）があれば、Gemini APIに渡して確定情報か判定。
4. 確定情報であれば、メールを生成・送信し、C1セルのステータスを反転。
5. 処理したURLをスプレッドシートの履歴列（A列またはB列）に追記。
