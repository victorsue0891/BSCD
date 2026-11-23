# BSCD · Raspberry Pi 光電磁電化學操作介面

以 **PyQt6 Widgets** 實作的離線桌面程式，目標設備為 **Raspberry Pi Compute Module 4（CM4）、Raspberry Pi OS 64-bit、800×600 螢幕**，也可在 Windows 開發與模擬。不需瀏覽器、網頁服務、線上字型或 ESP32 即可操作模擬器。ESP32 可於「連線」手動選擇，或以 `--port` 指定；部署設定的開機服務使用 `/dev/ttyACM0`。

公開 repository 包含執行程式、必要素材、測試、部署設定及測試用韌體紀錄 `RefTxt1006.txt`。文中提及的原始設計／硬體文件留在本機，不包含在 repository；執行程式及測試不依賴這些文件。

取得程式碼（保留既有部署設定使用的目錄名稱）：

```sh
git clone https://github.com/victorsue0891/BSCD.git Photoelectromagnetic-electrochemical
cd Photoelectromagnetic-electrochemical
```

## 啟動

在 CM4 安裝 Raspberry Pi OS 64-bit **含圖形桌面**的版本；官方下載頁目前列為 Debian Trixie 系列，實際安裝版號可用 `cat /etc/os-release` 確認。在圖形桌面的終端執行：

```sh
sudo apt update
sudo apt install python3-pyqt6 python3-pyqt6.qtserialport qt6-wayland fonts-noto-cjk
cd /path/to/Photoelectromagnetic-electrochemical
python3 main.py --demo
```

全螢幕操作：

```sh
sh start_pi.sh --demo
```

實機 UART 模式：

```sh
python3 main.py --fullscreen
```

指定 ESP32 串口並以全螢幕啟動：

```sh
python3 main.py --fullscreen --port /dev/ttyACM0 --line-ending LF
```

`--port` 在開機時自動連線；USB 尚未出現時每 2 秒重試，介面仍可操作。切換模擬、重播或開啟連線設定會取消等待。首次連線成功後若斷線，須手動重新連線，不會自動恢復量測。`--demo`、`--replay` 與 `--port` 互斥；換行可用 `--line-ending CRLF` 調整。

### Raspberry Pi 開機服務（pi 帳號、labwc 桌面）

完整的 Windows 打包／傳輸、Pi 套件安裝、串口權限、桌面自動登入、服務安裝與重新開機驗證流程，見 **[Raspberry Pi 部署與維護流程](deploy/README.md)**。文件也記錄 2026-11-03 實際部署結果與尚待確認的 ESP32 韌體回覆。

程式安裝於 `/home/pi/Photoelectromagnetic-electrochemical`，資料存於 `/home/pi/PIMEX/data`。先安裝上述 apt 套件，並啟用 `pi` 桌面自動登入；帳號須屬於 `dialout` 群組。以 `pi` 執行：

```sh
cd /home/pi/Photoelectromagnetic-electrochemical
mkdir -p ~/.config/systemd/user ~/.config/autostart ~/PIMEX/data
install -m 644 deploy/pimex.service ~/.config/systemd/user/pimex.service
install -m 644 deploy/pimex.desktop ~/.config/autostart/pimex.desktop
systemctl --user daemon-reload
systemctl --user enable pimex.service
sh deploy/start-session.sh
```

上面的 `sh deploy/start-session.sh` 應在 **Pi 本機圖形桌面的終端機**執行。若從 SSH 操作，請依部署文件確認 systemd 使用者環境已匯入桌面的顯示設定，再執行 `systemctl --user start pimex.service`。

`pimex.service` 以 pi 的 systemd 使用者服務執行，啟動參數包含全螢幕及 `/dev/ttyACM0`。labwc 的 XDG autostart 會在桌面就緒後匯入顯示環境並啟動此服務，避免在 Wayland 尚未就緒時啟動 GUI。程式退出後 5 秒重新啟動；需暫停時使用 `stop`。服務只開啟串口，不會自行開始量測；仍需收到 `FW_VERSION: 028` 才能開始實機 CV。

```sh
systemctl --user status pimex.service
journalctl _SYSTEMD_USER_UNIT=pimex.service -b
systemctl --user restart pimex.service
systemctl --user stop pimex.service
```

永久取消開機啟動時，需同時執行 `systemctl --user disable --now pimex.service`，並移走 `~/.config/autostart/pimex.desktop`。桌面入口與 service 設定原始檔保留在 `deploy/`。

在「連線」選擇裝置，例如 `/dev/serial0`、`/dev/ttyUSB0` 或 `/dev/ttyACM0`。串口採 **115200、8N1、無流量控制**；送出換行可選 LF 或 CRLF，須依實機確認。程式不會自動重置 ESP32，實機開始前必須收到 `FW_VERSION: 028`；若連線時錯過開機訊息，保持連線並重新啟動 ESP32。GPIO UART 需先由 Raspberry Pi OS 設定啟用並停用該埠的登入主控台。

OS 與 Qt6 套件依據：[Raspberry Pi OS 官方下載頁](https://www.raspberrypi.com/software/operating-systems/)、[Debian PyQt6 套件](https://packages.debian.org/trixie/python3-pyqt6)、[Debian QtSerialPort 套件](https://packages.debian.org/trixie/python3-pyqt6.qtserialport)、[Qt6 Wayland 平台套件](https://packages.debian.org/trixie/qt6-wayland)、[Qt QSerialPort 官方文件](https://doc.qt.io/qt-6/qserialport.html)。保留桌面環境預設的 Wayland／X11 選擇，不強制指定 Qt 平台。使用非阻塞 `readyRead` 事件，未在 UI 執行緒呼叫等待串口的阻塞函式。

Windows 開發：

```powershell
python -m pip install -r requirements.txt
python main.py --demo
```

Python 3.10 以上；早期 Windows 驗證環境為 Python 3.13.2、PyQt 6.11.0，2026-11-03 部署時的 Windows 驗證環境為 Python 3.14.0、PyQt 6.12.0。Raspberry Pi 使用系統 apt 安裝的 PyQt 6.9.0；不假設 PyPI 對每種 ARM 架構均提供 wheel。

## 操作

1. 在首頁選擇 CV 或 CA。
2. 設定參數。CV 只開放掃描速率、電壓上下限、階數；可載入／儲存 JSON 參數組。Next 只切換畫面，Start 才送出設備設定。
3. 設定 RGB。畫面順序為 R、B、G，送出命令固定為 **R G B**。這些值是 LED 控制值，未宣稱為校正光強。
4. 選取孔位：點孔選單孔、點欄號選整欄、點 A～H 選整列，或使用 Select all。
5. 按 Start。量測中孔位每 0.5 秒切換亮暗；收到該欄 END 且各孔至少有一筆資料，才標示該欄結束。進度按結束孔數計算，不推估資料點百分比。
6. 結束後點孔位進入整頁曲線；「＋／−」依序顯示／隱藏最後一次循環，不刪除資料。Save data 另存此孔所有循環的 CSV，Back 回到孔盤；孔盤 SAVE 另存整批。
7. CLR all 清除畫面選擇與目前顯示，再開始新批次。已建立的資料目錄保留；存檔失敗時需先將整批另存成功。

預設視窗為已確認的 **800×600**；在 CM4 螢幕上使用 `sh start_pi.sh` 全螢幕啟動。版面保留縮至 800×480 的相容性，也可向上縮放。數字可透過微調按鈕或鍵盤輸入；檔案對話框及檔名輸入使用作業系統的輸入設備／螢幕鍵盤。

## 外觀參考

逐張參考 `UI/UI 的圖片/01.jpg`～`15.jpg`：開機頁使用深藍紫色設備背景、白色標題及並排紫框 CV／CA 按鈕；設定頁採左右欄與波形示意，RGB 頁採 R／B／G 大色塊，孔盤右側集中選取、光源及操作按鈕，曲線改為整頁顯示。

開機背景由內建 imagegen 依 01.jpg 整理重建，移除筆電外框、瀏覽器提示與原有文字，因此不是原圖逐像素複製。Logo 沿用專案 HTML 的原始透明素材，原參考圖保持原檔。素材位置與提示詞說明見 [assets/README.md](instrument_ui/assets/README.md)。為保留必要操作，開機頁下方仍提供模擬、重播、連線及紀錄入口；測量中不能切換模式。

CV 設定頁依 D2 截圖保留完整欄位排列：上方 Ei／E Range、左側七列參數、右側雙三角波形與 Available Duration／Max. Accountable、底部空心方向箭頭及 Next／Reset。只有掃描速率、E1、E2、階數可編輯；其餘輸入框停用，未知值顯示「—」，Ei 顯示 Auto，Repeat 顯示實際固定值 1。紅框及紅字為參考圖的說明標記，不繪入正式操作畫面。數字以三位小數顯示，仍依既有參數範圍送出整數命令；初始／Reset 維持已驗證的 15、±2.5 V、1024，參考圖 2048 的韌體對應未確認，因此不新增此選項。

## 支援範圍

| 功能 | 模擬模式 | 實機 UART |
|---|---|---|
| CV 設定、RGB、曲線、存檔 | 支援 | 依 FW 028 紀錄實作，待設備驗收 |
| 任意孔位、整列、整盤選取 | 支援 | 只允許完整欄，每欄 8 孔 |
| 多欄量測 | 支援 | 依欄順序執行，上欄 END 後才下達下一欄 |
| CA 參數與衰減曲線 | 支援，合成資料 | 尚未啟用：N21～N24 未定義 |
| CV 峰值四組分色 | 僅展示 | 未啟用：物理量及正式算法未定義 |
| Stop | 模擬停止 | 送出 Q，等待 XSCAN_FUD END；未確認則逾時並鎖定重新開始 |
| 通訊紀錄重播 | 支援 FW 028 XS_FUD 格式 | 重播期間不連接實機 |

重播現有完整紀錄：

```sh
python3 main.py --replay RefTxt1006.txt
```

可解析 **8,208 筆、8 孔、每孔 1,026 筆**。最新紀錄的 `XS_FUD` 為 **X,Y**；`5,0` 是 **6A**，與 `RD_YXST Y X` 命令的順序不同。除錯行的整數 Average 不當成 AVG 樣本。

## 採用依據與暫定決策

優先採 FW 028 實測紀錄 `RefTxt1006.txt`、`QA-20261005D2.docx` 的四個設定欄位與 RGB 頁，再採 V9 與 D1；`QA-20261006.md` 用於追蹤未決項目。舊 HTML／圖片作版面與配色參考，不啟用已取消的 Ei、X%、平均 N、Repeat 輸入或 Excel 動態電壓算法。

| 對應問題 | 實作決策／限制 |
|---|---|
| N01、N06 | CV 階數暫列 256／512／1024；初始／Reset 為 15 mV/s、+2.5／−2.5 V、1024，採最新成功案例。256／512、非對稱範圍仍需實機驗證。 |
| N02～N04 | VRE、AVG、T **保留原值**；曲線與 CSV 不擅自標成 V、A、mA、秒或毫秒。參數輸入的 V／mV/s 與量測原值分開處理。 |
| N07、N08 | 不傳選填 VREF／INCR，不由 Pi 重建掃描階碼或時序。 |
| N13、N14 | 實機只允許完整欄；循環命令值固定 1，逐欄執行。固定 1 是暫定實作決策，不是已確認需求。 |
| N15 | Start 送 APPCFG_RST；收到 OK、REAL_STEP／STEP_TIME 及 APPVREF_RST／APPVBASE_RST 後才送 VRE_XSCAN_FUD。 |
| N16、N17 | 設定／開始／停止等待上限 8 秒，量測資料靜默上限 30 秒，均為主機策略。逾時不重送掃描；送 Q 並保留部分資料。硬體停止未確認時，需要操作者確認設備停止，再清除連線並重連。 |
| N18 | 本批共用 RGB，隨每欄掃描命令送出。結果著色只畫於 UI，未另送 LEDRGB_RST／LEDYX_RST。LED 關閉與停止後電壓狀態須由韌體契約定義。 |
| N19、N11 | END 代表收到結束訊息；沒有正式預期筆數契約，未宣稱已驗證完整性。樣本不任意刪除、去重或濾除突增值。 |
| N21～N24 | CA 只模擬初始／目標電位、持續時間與取樣間隔。暫未做每欄獨立設定、欄間複製，或將 dt 猜成命令 N。 |
| N25～N28 | 展示分色取遞增 VRE 段的帶符號最大 AVG，再平均各循環；同值按孔位排序、餘數優先分給前組。實機不套用此暫定算法，不自行設定 XX V 門檻。 |
| N30～N35 | 採每孔 CSV、批次 JSON、完整 UART JSONL；預設自動保存，並保留手動 Save。Pi 檔案不宣稱與 ESP32 SD 卡同步。 |
| N36～N38 | 使用者已確認 CM4、最新版 Raspberry Pi OS 64-bit、800×600；ESP32 連接埠仍待設備端確認。未連接實際 Raspberry Pi、RTC、螢幕或 ESP32；磁場控制沒有對應文件，因此未加入控制命令。 |

CA 模擬器內部重用 XS_FUD 訊息結構，**不是正式 CA 通訊協定**。合成資料採加速播放，不用來驗證實際速率、電流或電壓。

## 資料保存

預設儲存於使用者家目錄下 `PIMEX/data/`，可修改：

```sh
python3 main.py --demo --data-dir /home/pi/pimex-data
```

每次 Start 先建立唯一批次目錄，再送命令：

```text
YYYYMMDDhhmmss_CV_<batch_id>/
  uart.jsonl                    # 主機時間、RX/TX、原始訊息；逐行 flush
  metadata.json                 # 設定、來源、FW、狀態、孔位、原始單位待確認
  YYYYMMDDhhmmss_export_<unique>/
    YYYYMMDDhhmmss_6A.csv        # 此孔所有循環、原始數值與原始量測行
    ...
    metadata.json
```

時間使用 **Asia/Taipei（UTC+8）**，取批次開始時間；每次另存建立新目錄，避免同秒重名或重存覆寫。程式讀取 Linux 系統時間，DS3231 須由作業系統完成校時／同步；本程式不自行存取 I²C RTC。

RX/TX 在量測中持續寫入；正常結束、中止及錯誤時自動匯出 CSV。異常斷電後可查看 `uart.jsonl` 已落盤的內容；逐行 flush 不等於斷電保證，尚未提供啟動後自動恢復歷史批次功能。紀錄重播目前接受原始 `.txt`／`.log` 的 FW 028 文字輸出。

若儲存失敗，停止排程並保留記憶體資料，畫面顯示錯誤；需 Save data 到可寫入的位置後才可清除或離開。外接 USB 可直接在 Save data 對話框選擇已掛載目錄。

## 連線診斷與 USB／SD 卡匯出

2026-11-23 新增程式啟動起的診斷紀錄，不必先進入「通訊紀錄」或按 Start。預設存於 `~/PIMEX/diagnostics/`，與量測資料 `~/PIMEX/data/` 分開；每次啟動建立新的 `session_時間_識別碼/`。若自訂 `--data-dir`，診斷目錄預設為該資料夾的同層 `diagnostics/`，也可明確指定：

```sh
python3 main.py --fullscreen --port /dev/ttyACM0 --data-dir /home/pi/PIMEX/data --diagnostics-dir /home/pi/PIMEX/diagnostics
```

**本版以記錄與診斷為主，不新增 ESP32 握手命令。** 串口成功開啟後顯示「等待主板版本」；收到 `FW_VERSION: 028` 才允許開始實機 CV。不傳送 ACK／READY／版本查詢，不要求主板改成每 10 ms 重送。收到主板重新開機訊息時清除原版本確認，量測中仍走既有故障處理。重複版本訊息會完整送入診斷佇列，介面合併連續重複的狀態文字。若主板只送一次且發生在串口開啟之前，Pi 無法補回該訊息，仍須保持連線後重啟主板。

診斷包含主機時間與單調計時、串口設定／開關／錯誤、RX 原始位元組（十六進位）、解析前文字行、版本接收、TX 排入佇列／實際寫出位元組數、量測狀態及批次資訊。無效字元與尚未成行的資料仍可從原始 RX 查到。TX 寫出不代表 ESP32 已收到或接受命令；RX bytes 與文字行是同一份資料的不同表示，不可重複計為樣本。

提供紀錄給 ESP32 工程師：

1. 將 USB 隨身碟或 USB SD 卡讀卡機插入 Pi，讓桌面掛載儲存裝置。
2. 開啟首頁「通訊紀錄」，選擇「本次執行」或歷史紀錄。
3. 選擇掛載裝置；未出現時按「重新整理」，也可用「選擇資料夾」選取 `/media/pi/裝置名稱` 下的目錄。
4. 按「匯出診斷 ZIP」。背景匯出有進度與取消功能；量測與紀錄可繼續，視窗內「停止量測」仍可使用。匯出的是按下後建立的固定快照，後續新紀錄需再匯出一次。
5. 等待顯示「已完成並檢查」，取得 `PIMEX_debug_時間_識別碼.zip`；再由桌面檔案管理員卸載裝置後拔除。程式不會自動卸載。

| ZIP 內容 | 用途 |
|---|---|
| `summary.txt` | 快照時間、版本雜湊、紀錄缺漏及解讀限制 |
| `manifest.json` | 執行環境、啟動設定、程式碼 SHA256、各原始分段 SHA256、輪替／丟棄計數 |
| `uart.txt`／`uart.jsonl` | 可讀通訊紀錄／結構化 UART 事件；不是既有「紀錄重播」的輸入格式 |
| `events.log` | 啟動、版本、狀態、錯誤等事件（每行 JSON） |
| `batch_metadata.json` | 快照內涉及的批次資訊；沒有量測時為空 |
| `raw/records-*.jsonl` | 未修改的原始診斷分段，用於追查解析前資料 |

診斷包不取代 CSV 或原有量測批次的 `uart.jsonl`，也不會自動收集量測 CSV 或 systemd journal。批次 `metadata.json` 的 `settings_reply.diagnostics_session` 可對應診斷工作階段。

保存採背景寫入，佇列上限 8,192 筆；每段約 20 MiB，診斷分段合計目標上限 500 MiB，超過時清除最舊分段，**不清除量測資料**。目前寫入分段、匯出快照與其他正在執行的程式工作階段受到保護，因此用量可能暫時超過目標。歷史紀錄可能只剩尾段，請由 `pruned_segments` 判斷；空工作階段的中繼資料最多保留最新 100 份。

正常約每秒 flush；斷電、強制結束仍可能遺失尾端紀錄，不能保證每筆落盤。佇列滿或寫入失敗時，畫面及診斷包會標示不完整；診斷失敗不另行中斷量測，原有量測存檔失敗的保護仍保留。修復診斷儲存問題後需重啟程式。匯出需要 Pi 的暫存空間與目的地可用空間；磁碟滿、拔除、唯讀或取消時顯示失敗／取消，保留 Pi 原始紀錄。尚未完成的 `.zip.partial` 不可視為成功檔案，裝置突然拔除後可能需手動移除殘留檔。

## 程式結構與驗證

```text
main.py                        入口與命令列參數
instrument_ui/app.py           操作流程、參數組、程式入口
instrument_ui/screens.py       依參考圖片配置各頁版面與樣式
instrument_ui/visuals.py       開機畫面與波形示意繪製
instrument_ui/assets/          開機背景、原始 Logo 與來源說明
instrument_ui/widgets.py       96 孔盤、整頁結果與 Qt 原生曲線繪製
instrument_ui/controller.py    狀態機、設定確認、多欄排程與錯誤保留
instrument_ui/transports.py    非阻塞 UART、模擬器、紀錄重播
instrument_ui/protocol.py      ASCII 分行及 FW 028 訊息解析
instrument_ui/domain.py        參數、孔位、量測批次、展示排名
instrument_ui/storage.py       UART 日誌、每孔 CSV 與批次資訊
instrument_ui/diagnostics.py   背景診斷、輪替與 ZIP 快照匯出
instrument_ui/diagnostics_ui.py 通訊紀錄、掛載裝置選擇與背景匯出介面
tests/                         紀錄、狀態機、存檔與 UI 流程測試
```

執行驗證：

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

測試涵蓋完整現有紀錄、UART 拆包／黏包、XY 對應、浮點數與非法資料、設定確認順序、多欄排程、中止／逾時、重新開機、磁碟寫入失敗、截斷紀錄、CA 模擬、CSV 重存及 800×600／800×480 UI 完整操作流程。通過軟體測試不等於完成設備驗收；實際電壓／電流換算、UART 換行、停止回覆、韌體時序與 RTC 仍須連接設備確認。

診斷測試另涵蓋量測前原始 UART、重複版本不新增命令、快照與歷史匯出、佇列溢位、輪替、診斷寫入失敗，以及模擬裝置移除／取消／空間不足；也確認匯出時模擬量測仍可完成。實際 USB 拔插、Pi 上的效能及現場 ESP32 時序仍須在更新部署後驗證。

2026-11-23 本機驗證結果：`40 passed`，包含匯出期間仍可停止量測；此結果不代表新版已安裝到 Pi。
