# Third-Party Notices

EverStickyNote に同梱または実行時に利用する第三者ソフトウェアのライセンス情報です。
本プロジェクトのソースコード自体は [MIT License](LICENSE) です。

## PySide6 / Qt for Python

- **用途:** GUI（ウィンドウ、システムトレイ、ウィジェット）
- **ライセンス:** GNU Lesser General Public License v3.0 (LGPL-3.0)
- **参照:** https://www.qt.io/qt-for-python  
  https://www.gnu.org/licenses/lgpl-3.0.html  
  https://www.qt.io/licensing/

LGPL-3.0 の下で PySide6 を利用しています。本プロジェクトの Python ソースは MIT ですが、**配布物（EXE など）に Qt のライブラリが含まれる場合**は、LGPL が要求する提供義務（対象ライブラリの再リンク可能性の確保、ライセンス文の同梱など）に従ってください。詳細は Qt の公式ライセンス説明を参照してください。

## evernote3

- **用途:** Evernote EDAM API クライアント（レガシー経路・テスト用コード）
- **ライセンス:** Apache License 2.0
- **参照:** https://pypi.org/project/evernote3/

## Apache Thrift

- **用途:** evernote3 の通信プロトコル依存
- **ライセンス:** Apache License 2.0
- **参照:** https://thrift.apache.org/

---

## Apache License 2.0（抜粋）

evernote3 および Apache Thrift は Apache License 2.0 の下で提供されています。
配布時は、必要に応じて各プロジェクトの NOTICE ファイルおよび LICENSE 全文を同梱してください。

```
Copyright notices and license texts are retained in the respective
upstream projects. This application uses those components as dependencies
and does not claim copyright over them.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```
