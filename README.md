# EverStickyNote

Evernote デスクトップアプリのローカルデータから、指定したノートブックのノートを読み取り専用の付箋として表示します。編集は Evernote 側で行い、このアプリは書き戻しません。

## 必要なもの

- Windows
- ログイン済みの Evernote デスクトップアプリ
- 64-bit の Python 3.12（PySide6 は 32-bit では入りません）

## 起動

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

## 設定

`config.toml` に、付箋として出すノートブック名を Evernote 上の表示名どおりに書きます。複数指定できます。

```toml
notebooks = ["2-30. 付箋"]
```

付箋の位置と、本体ウィンドウを最小化で閉じたかは `position.toml` に保存され、次回起動時に復元されます。このファイルは端末ごとの状態なので、リポジトリには含めません。

## 付箋の操作

- 上の行をドラッグして移動します。ダブルクリックすると、そのノートを Evernote で開きます。
- 「色」で背景色を切り替えます。
- 「最前面」で、最前面固定のオンとオフを切り替えます。ウィンドウは閉じません。
- 「閉じる」は付箋を隠すだけで、Evernote のノートは削除しません。
