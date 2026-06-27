声吉 Windows版

インストール方法

1. このzipを展開します。
2. Install-KoeKichi.cmd をダブルクリックします。
3. 初回セットアップでマイク、起動キー、Whisperモデル、文字起こしモード、ログイン時起動を選びます。
4. 完了したら、スタートメニューの Koe Kichi から起動します。

既定の操作

- Altキーを素早く2回押す: 録音開始
- もう一度 Altキーを素早く2回押す: 録音停止、文字起こし、現在の入力先へ貼り付け
- マウスの中央クリック: 安定性のため既定では無効です。設定画面で有効にできます。
- 録音中: カーソル付近に小さいHUDが表示され、音量バーが動きます。
- 処理中: HUDがプログレス表示に切り替わります。
- 処理完了後: HUDは自動で消えます。
- 設定: タスクトレイの Koe Kichi アイコン、またはHUD右クリックから「設定」を開きます。
- 終了: HUDを右クリックして「終了」、またはタスクトレイの Koe Kichi アイコンから Exit。

文字起こし速度

- 既定で4秒チャンク先読みが有効です。
- 録音中に一部の音声をバックグラウンドでWhisperへ渡し、停止後の待ち時間を短くします。
- 短い録音や先読み失敗時は、従来の全文文字起こしへ自動で戻ります。
- ログには transcription mode として streaming_prefetch または full が記録されます。

Whisperモデル

- 既定は small です。CPUのみのWindowsマシンで速度と精度のバランスを取りやすい設定です。
- 設定画面から small、medium、large-v3、turbo を選べます。
- turbo は large-v3 系の高速モデルですが、small より大きいためCPU環境では常に速くなるとは限りません。
- モデル変更後、次回のローカル文字起こし時に必要なモデルが読み込まれます。

Gemini API入力

- 既定ではローカルWhisperを使います。
- 追加実験として、録音停止後にWAVをGemini APIへ1回だけ送って文字起こしできます。
- スタートメニューの Koe Kichi Settings で Transcription backend を Gemini API に変更します。
- 既定では環境変数 GEMINI_API_KEY を使います。
- 設定画面の Gemini API key 欄にキーを貼り付けると黒点で表示され、保存するとユーザー環境変数に保存されます。
- APIキー本体は設定ファイル、辞書、履歴、配布zipには保存しません。
- Gemini APIへ送る場合は、既定で「えー」「あのー」などのフィラーを除いた文字起こしを依頼します。
- Gemini APIで失敗した場合は、既定でローカルWhisperへ自動で戻ります。
- ログには transcription mode として gemini_audio または full_after_gemini_fallback が記録されます。

辞書と履歴

- タスクトレイの Koe Kichi アイコンを右クリックすると「設定」「辞書登録」「履歴」を開けます。
- 辞書登録では「読み方」と「単語」を登録できます。
- 履歴では過去の文字起こし結果をクリックするだけでコピーできます。
- 初期辞書には OpenAI、声吉、Whisper、ChatGPT、Ollama、Codex、Python、GPU、CPU、Alt、ハルシネーション などの例を入れています。

初期設定

- インストール中にマイク、起動キー、Whisperモデル、文字起こしモードを選択できます。
- ログイン時に声吉を自動起動するか選択できます。
- 既定の起動キーは Alt のダブルタップです。
- 起動時のモデル事前読み込みは既定で無効です。初回認識時にモデルを読み込みます。
- あとから変更する場合は、タスクトレイの Koe Kichi アイコンから「設定」を開くか、スタートメニューの Koe Kichi Settings を開きます。

アンインストール

- zip内の Uninstall-KoeKichi.cmd をダブルクリックするとアンインストールできます。
- インストール後はスタートメニューの Uninstall Koe Kichi からもアンインストールできます。
- 既定では設定、辞書、履歴は残します。完全に削除したい場合は scripts\windows_uninstall.ps1 に -RemoveUserData を付けて実行します。

保存場所

- アプリ本体: %LOCALAPPDATA%\KoeKichi
- 設定と辞書: %APPDATA%\KoeKichi
- Whisperモデルキャッシュ: 通常は %USERPROFILE%\.cache\huggingface

スタートメニュー

- Koe Kichi: 本体起動
- Koe Kichi Settings: マイク、起動キー、Whisperモデル、文字起こしモード、ログイン時起動の変更
- Koe Kichi Setup Check: 音声デバイスとモデルの再確認
- Koe Kichi Diagnose: 診断情報を表示
- Uninstall Koe Kichi: アンインストール

注意

- 初回インストール時はネットワーク接続が必要です。
- Python 3.11 が見つからない場合、winget が利用できる環境では自動インストールを試みます。
- 会社PCなどでwingetやPowerShell実行が制限されている場合は、先にPython 3.11を手動で入れてから再実行してください。
- 声吉本体はMIT Licenseです。依存ライブラリのライセンスは THIRD_PARTY_NOTICES.md を確認してください。
