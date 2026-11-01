# EverStickyNote

Evernote デスクトップアプリのローカルデータから、指定したノートブックのノートを読み取り専用の付箋として表示します。編集は Evernote 側で行い、このアプリは書き戻しません。

## 必要なもの

- Windows
- ログイン済みの Evernote デスクトップアプリ
- 64-bit の Python 3.12（PySide6 は 32-bit では入りません）

## フォルダ構成

```
EverStickyNote/
├── README.md
├── pyproject.toml              # パッケージ定義（版は src/everstickynote/__init__.py）
├── requirements.txt
├── build.ps1                   # ビルドの入口。dist\ に配布物を作る
├── config/                     # 配布する設定ファイルの原本（Git 管理）
│   └── config.toml
├── src/                        # ソースコード（Git 管理）
│   └── everstickynote/
│       ├── __main__.py         # python -m everstickynote の入口
│       ├── main.py
│       ├── ui/
│       └── assets/             # アプリアイコン
├── tests/
├── build/                      # 中間ファイル（Git 管理外）
└── dist/                       # build.ps1 が作る（Git 管理外）
    ├── EverStickyNote/         # EverStickyNote.exe、config.toml、README.md など
    └── EverStickyNote-v1.1.0.zip
```

## セットアップ

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
```

## 起動（ソースから）

```powershell
.\.venv\Scripts\python.exe -m everstickynote
```

## テスト

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_single_instance tests.test_evernote_client tests.test_local_notes tests.test_local_store tests.test_local_ui tests.test_notebook_config tests.test_sync tests.test_ui tests.test_window_position
```

## ビルド

```powershell
.\build.ps1
```

`dist\EverStickyNote\` に EXE と `config.toml`（`config\` からコピー）などがそろい、その中身を固めた `dist\EverStickyNote-v<版>.zip` もできます。

## 設定

設定ファイル `config.toml` は、EXE で動かすときは EXE と同じフォルダ、ソースから動かすときはプロジェクトのフォルダ（このファイルと同じ場所）から読みます。ソースから動かす場合は、原本 `config\config.toml` をコピーし、付箋として出すノートブック名を Evernote 上の表示名どおりに書きます。複数指定できます。プロジェクト直下の `config.toml` は端末ごとの設定なので、リポジトリには含めません（無ければ起動時にひな形を作ります）。

```powershell
copy config\config.toml config.toml
```

```toml
notebooks = ["ノートブック名"]
```

付箋の位置と、本体をトレイに格納したかは `config.toml` と同じフォルダの `position.toml` に保存され、次回起動時に復元されます。このファイルは端末ごとの状態なので、リポジトリには含めません。本体はタスクバーではなく通知領域（システムトレイ）に表示します。

## 付箋の操作

- 上の行をドラッグして移動します。ダブルクリックすると、そのノートを Evernote で開きます。
- 「整列」で、開いている付箋を画面の右上から下へ、はみ出したら左の列へ並べます。押した付箋が先頭（右上）になります。
- 「色」で背景色を切り替えます。
- 「最前面」で、最前面固定のオンとオフを切り替えます。ウィンドウは閉じません。
- 付箋の「閉じる」は、その付箋をタスクバーへ最小化します。Evernote のノートは削除しません。
- 本体ウィンドウの「開く」、または一覧の付箋名をダブルクリックすると、最小化・非表示にした付箋を再表示します。
- 本体ウィンドウの「閉じる」は、一覧で選んだ付箋をタスクバーへ最小化します。
- 本体ウィンドウはタスクバーではなくシステムトレイに格納されます。トレイアイコンをダブルクリックするか、右クリックメニューからメインフォームを開けます。
- 本体ウィンドウの × を押すと終了確認が出ます。はいを選ぶとアプリを終了します。
- 二重には起動しません。すでに動いているときに起動すると、動いている方のメインフォームを表示します。

## ライセンス

本リポジトリのソースコードは [MIT License](LICENSE) の下で公開しています。

## 第三者ライセンス

本アプリは次のオープンソースソフトウェアを利用しています。

| 名称 | 用途 | ライセンス |
|------|------|------------|
| [PySide6](https://www.qt.io/qt-for-python) | GUI | [LGPL v3](https://www.gnu.org/licenses/lgpl-3.0.html) |
| [evernote3](https://pypi.org/project/evernote3/) | Evernote API クライアント（レガシー経路） | Apache License 2.0 |
| [Apache Thrift](https://thrift.apache.org/) | evernote3 の依存 | Apache License 2.0 |

詳細な第三者ライセンスの記載は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を参照してください。EXE を配布する場合、PySide6（LGPL v3）に関する要件にも留意してください。

## アプリアイコン

`src/everstickynote/assets/app-icon.png` および `src/everstickynote/assets/app-icon.ico` は、作者（Dowargon）が本プロジェクト用に作成したものです。MIT License と同じ条件で、本リポジトリに含まれる範囲で利用できます。

## 免責・商標

- 本ソフトウェアは Evernote 社の公式製品ではありません。Evernote デスクトップアプリのローカルデータを**非公式**に読み取る方式です。Evernote のアップデートや利用規約の変更により、動作しなくなる可能性があります。利用は自己責任でお願いします。
- 「Evernote」および Evernote のロゴは、Evernote Corporation の商標または登録商標です。本プロジェクトは Evernote 社とは無関係です。
