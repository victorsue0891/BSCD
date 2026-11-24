# ESP32 工程師測試與 Debug SOP

適用於 **BSCD／PIMEX Pi 操作介面與 ESP32 FW 028** 的整合測試。目標是讓每次問題都有可重現的步驟，以及能對照的 Pi／主板紀錄。本文件描述目前程式行為，不代表實機已通過驗收。

**本階段以 Log 觀察為主，不要求修改 ESP32 CODE。** Pi 收到版本訊息後不會傳送 ACK、READY 或版本查詢；不要求主板改為每 10 ms 重送版本。現有量測命令仍為 `APPCFG_RST`、`VRE_XSCAN_FUD`，停止命令為 `Q`。

首次測試先完成第 1～4 節，接著依第 5 節執行各案例。問題發生後先保存第 6 節證據，再按第 7～9 節分析及恢復。

## 1. 測試前準備

| 項目 | 確認內容 |
|---|---|
| Pi 程式 | 已依 [Connect 部署 SOP](CONNECT-SOP.md) 更新；「通訊紀錄」內有「匯出診斷 ZIP」按鈕。只有舊版訊息視窗時，先更新。 |
| 遠端操作 | Raspberry Pi Connect 的 Screen sharing 用於操作介面；Remote shell 用於查詢服務與收集系統資訊。所有 shell 指令在 Pi 以 `pi` 執行。 |
| 主板識別 | 記錄板號／硬體版本、韌體版本、燒錄檔或 firmware commit、USB 接法與供電方式。只寫「028」可能無法區分不同編譯。 |
| 串口 | `/dev/ttyUSB0`、115200、8 data bits、No parity、1 stop bit、無流量控制。Pi 預設送出 LF。 |
| 接收換行 | Pi 以 LF 分行，可接收 LF 或 CRLF；只有 CR 不會完成一行。 |
| 測試負載 | 使用工程師確認可接受測試電壓／光源設定的測試板或負載；涉及拔線、重啟與逾時的案例安排在可中斷的測試環境。 |
| 外接儲存 | 準備可寫入的 USB 隨身碟或 USB SD 卡讀卡機，由 Pi 桌面掛載；此處指外接媒體，不是取出 Pi 的系統卡。 |
| 串口占用 | 測試期間只由 PIMEX 開啟同一串口。不要另開 Serial Monitor、minicom、screen 或 `cat /dev/ttyUSB0`，避免競爭／分走接收資料。 |

在 Remote shell 記錄以下輸出，測試中不要更新程式或更換韌體，以免前後版本混在一起：

```sh
date -Is
git -C /home/pi/Photoelectromagnetic-electrochemical log -1 --oneline
git -C /home/pi/Photoelectromagnetic-electrochemical status --short
systemctl --user status pimex.service --no-pager
systemctl --user show pimex.service -p MainPID -p ActiveState -p SubState -p NRestarts
ls -l /dev/ttyUSB0
id -nG pi
df -h /home/pi
```

若舊目錄不是 Git repository，記錄此情況並先確認部署版本。`git status --short` 有內容表示有本機異動，也要附上。不要只根據 GitHub 最新 commit 推定 Pi 正在執行相同版本。

Pi 預設資料位置：

- `/home/pi/PIMEX/diagnostics/`：每次程式啟動一個診斷工作階段，包含量測之前的通訊。
- `/home/pi/PIMEX/data/`：每次 Start 的批次、量測 UART、metadata 與 CSV。

若服務有自訂 `--data-dir`／`--diagnostics-dir`，以 `systemctl --user cat pimex.service --no-pager` 的設定為準。診斷從程式啟動即開始；不用先進入訊息視窗才接收 UART。

## 2. 上電與版本接收測試

1. 讓 Pi 完成桌面登入，確認 PIMEX 服務已啟動。
2. 在首頁查看串口狀態；必要時開「連線設定」，選 `/dev/ttyUSB0`、LF，再按「連接 UART」。不要誤選模擬器。
3. 記下主板上電／Reset 的實際時間。若主板還未上電，先上電；若已經錯過版本訊息，確認主板未在量測，再按硬體允許的方式 Reset。
4. 觀察首頁狀態，並在「通訊紀錄」確認 `FW_VERSION: 028`。
5. 尚未按 Start 前，匯出一份診斷 ZIP，作為純開機／連線基準。

| Pi 畫面／證據 | 正確解讀 |
|---|---|
| 等待串口裝置 | 尚未成功開啟串口；啟動參數指定的裝置未就緒時，程式每 2 秒嘗試。 |
| 串口已開啟 · 等待主板版本 | 作業系統已開啟裝置，但尚未解析到支援的版本訊息。不能據此宣稱雙向通訊成功。 |
| 已收到主板版本 · FW 028 | Pi 已收到支援版本，可以繼續設定實機 CV；Start 還受到選孔、忙碌與舊批次等條件限制。 |
| 版本不支援 | 版本行已被辨識，但版本字串不是 `028`，實機 CV 不允許開始。 |
| 連線異常／停止狀態待確認 | 先保存 Log 並確認主板狀態，依第 9 節恢復；不要直接重複按 Start。 |

目前辨識的是 `FW_VERSION: 028`，不能把其他如 `FW...28` 的文字縮寫當成等效格式。未知文字仍會保留於診斷紀錄，但不一定顯示在簡化的狀態訊息視窗。

**上電順序的限制：**若主板只在開機送一次版本，且發生在 Pi 開啟串口前，就可能漏接。即使「Pi 先開」，主板上電後 USB 裝置才出現，也仍有 USB 列舉／開埠的時間差。Reset 若會使 USB 斷線，不能假設 Pi 持續持有原串口；首次成功連線後再斷線，目前需要手動重連，不會自動恢復量測。

記錄「Pi 先開／主板先開／同時上電」、「Reset 是否讓 `/dev/ttyUSB0` 消失」、「是否重新連接 UART」。若始終無法在開埠後收到版本，將此列為待協調的啟動時序問題，不宣稱此次 Log 功能已解決握手。

## 3. 單欄 CV 基準測試

先只測一欄，成功後再擴大。以下數值對照既有 [FW 028 紀錄](../RefTxt1006.txt)，實際執行前仍由硬體工程師確認測試負載允許這組設定。

| 設定 | 基準案例 |
|---|---|
| 模式 | CV；CA 實機目前未啟用 |
| 掃描速率 | 15 mV/s |
| 電壓上限／下限 | +2.5 V／−2.5 V |
| 階數 | 1024 |
| RGB | 依測試計畫記錄；下方既有紀錄範例為 R=255、G=255、B=255 |
| 孔位 | 第 6 欄完整 8 孔：6A～6H；命令使用 `X=5` |
| 重複次數 | Pi 目前固定送 1 |

操作步驟：

1. 確認是實機連線且已收到 FW 028。若顯示 DEMO／REPLAY，不能用這次結果驗收主板。
2. 選 CV，設定參數、RGB，再選第 6 欄整欄；實機不支援只選其中一孔。
3. 記下按 Start 的時間，只按一次。單純按 Next 切頁不會送量測設定。
4. 等待該欄結束，記錄結果、批次 ID、各孔筆數及檔案位置；不要以「畫面有曲線」作為唯一判準。
5. 另存所需 CSV，並匯出涵蓋開始到結束的診斷 ZIP。完成後才按 CLR all 準備下一次測試。

正常命令順序如下。這是 Log 判讀範例，**不是要在 Pi shell 貼上執行的指令**；其中回覆數值為既有案例，不要求所有設定都回相同數值。

```text
ESP32 -> Pi: FW_VERSION: 028
             （Pi 不回傳新的版本確認命令）
             （使用者按 Start）
Pi -> ESP32: APPCFG_RST 15 2500 -2500 1024
ESP32 -> Pi: APPCFG_RST OK
ESP32 -> Pi: REAL_STEP=1024 STEP_TIME=651
ESP32 -> Pi: APPVREF_RST=512 APPVBASE_RST=0
Pi -> ESP32: VRE_XSCAN_FUD 5 255 255 255 1
ESP32 -> Pi: VRE_XSCAN_FUD OK
ESP32 -> Pi: XSCAN_FUD START T:40175
ESP32 -> Pi: XS_FUD (1/1): 5,0 VRE=0 AVG=3.526562 T:42324
             （其餘量測資料；應包含本欄 8 孔）
ESP32 -> Pi: XSCAN_FUD END T:<整數> ELAPSED:<整數>
```

Pi 的實際判斷條件：

- 收到 `APPCFG_RST OK`，並收齊 `REAL_STEP`、`STEP_TIME`、`APPVREF_RST`、`APPVBASE_RST` 四個欄位後，才送掃描命令；設定回覆順序可不同，但文字需符合現有解析格式。
- `VRE_XSCAN_FUD OK` 本身不會讓 Pi 進入量測中；還需要 `XSCAN_FUD START T:<整數>`。
- `XS_FUD` 座標是 **X,Y**：X=0～11、Y=0～7，`5,0` 對應 **6A**。不要套用其他命令的 Y,X 順序。
- RGB 命令順序固定為 **R G B**，雖然介面排列是 R、B、G。三色相同的案例無法辨識交換問題；基本流程通過後，再用工程師同意的三個不同數值測一次。
- 收到 END 且本欄每孔至少一筆資料，Pi 會標示該欄完成。這不是完整筆數驗證；既有紀錄的每孔 1,026 筆只是該案例觀察值，不是所有設定的通用驗收標準。
- `VRE`、`AVG`、`T` 保留原值。沒有已確認的校正／單位契約前，不直接當成伏特、安培或毫秒驗收；Pi 的主機時間另見診斷欄位。

## 4. Stop 與逾時確認

另開一個可中斷的測試批次，確認已進入量測中後按 Stop，記錄時間。

| 階段 | Pi 行為 | 工程師要確認的證據 |
|---|---|---|
| 按 Stop | 送 `Q`，進入 `stopping` | 查 TX 事件與主板端是否實際收到 Q；確認實際輸出狀態。 |
| 收到停止結束訊息 | `stopping` 狀態收到 `XSCAN_FUD END ...` 時，標示 `interrupted`、保留部分資料 | 保存 END 原文、批次狀態與 CSV。 |
| 設定／開始／停止等待 | 每個狀態等待上限 8 秒 | 超時會出現 `response_timeout`，對照它的 `state`。一般文字或 OK 不一定滿足轉態條件。 |
| 量測中 | 自進入 running 或最後一筆有效且屬於當欄的樣本起，30 秒沒有下一筆即逾時 | 持續收到 FW／除錯文字不會重設這個樣本等待計時。 |
| 實機量測異常 | 保留部分資料、嘗試送 Q，停止狀態待確認 | 不會自動重送掃描命令或自動續測；停止逾時後可能再看到故障處理送出的 Q。 |

8 秒／30 秒是目前 **Pi 的等待策略**，不是已確認的主板性能規格；若實測合法流程超過時間，提出量測證據再協調。`interrupted` 或 END 也不證明電壓、光源等實體輸出都已關閉，實際停止後狀態需由硬體工程師確認。

## 5. 測試案例表

每一案例填 Pass／Fail／未測，保留獨立測試編號。一次只改一個條件，異常後先匯出，不要連續重啟把事件混在一起。

| 編號 | 操作 | 目前預期／觀察重點 |
|---|---|---|
| T01 開機接收 | Pi 啟動後再讓主板上電或 Reset；不按 Start | 查開埠與 FW 接收的先後，收到 FW 不會多送確認命令。把 USB 重新列舉列入觀察。 |
| T02 反向順序 | 主板先啟動，再啟動 Pi 程式 | 若一次性 FW 早於開埠，可能一直等待版本；記錄是否可重現及恢復方式。這是現況限制，不是要求它一定自動成功。 |
| T03 單欄 CV | 依第 3 節 | 設定回覆齊全、START 在樣本之前、座標正確、8 孔都有資料、END 後保存資料。 |
| T04 Stop | 量測中按 Stop | 查 Q、停止回覆及實際停止狀態；無回覆時應逾時並保留部分資料。 |
| T05 兩欄 CV | 單欄成功後選兩個完整欄 | Pi 按 X 由小到大，上一欄 END 後才送下一欄；批次設定共用，不是每欄重送 APPCFG_RST。 |
| T06 重複版本 | 只有現有韌體本來就會重複送 FW 時才執行 | 查逐筆接收紀錄、介面是否可操作、沒有新 ACK；不為本案修改韌體或人工用第二個終端注入訊息。無此條件填未測。 |
| T07 USB 斷線 | 可中斷的測試批次中拔除主板通訊 USB；記錄 USB 是否也供電 | 出現串口錯誤時應保留部分資料／停止狀態待確認，重插後不自動續測。若沒有可辨識的串口錯誤，可能由樣本逾時偵測；主板仍可能繼續工作。 |
| T08 主板 Reset | 可中斷的測試批次中 Reset；記錄是否造成 USB 重列舉 | 若 Pi 收到 `ESP-ROM:`／`rst:0x...` 開機行，會當作主板重啟；量測中進入故障。若只看到 FW 028，Pi 不會單憑重複 FW 認定重啟；無明確訊息時需對照外部觀察。 |
| T09 診斷匯出 | 先本機資料夾、再掛載 USB／讀卡機匯出 | ZIP 可在工程師電腦解壓；紀錄涵蓋本次事件；匯出中仍可使用「停止量測」。 |
| T10 匯出取消 | 按匯出後取消；先於無正式量測時測試 | 取消有提示、Pi 原始紀錄仍在。若檔案很小已先完成，記為已完成，不當作取消失敗。 |

診斷寫入失敗／空間不足／匯出裝置移除已有軟體故障注入測試，不等於實際設備已驗證。需要實體異常測試時，使用可犧牲的外接媒體及測試批次；不要為測試填滿 Pi 系統碟或拔除其系統卡。

## 6. 問題發生後保存哪些資料

### 6.1 先記錄現象

記下測試編號、操作者、故障時間（含時區）、最後一次操作、畫面文字、主板狀態。拍攝／截取問題畫面。時間不準也要註明；Pi 與主板時間不同不能直接相減當成通訊延遲。

確認硬體停止狀態後，優先匯出故障當次紀錄。若程式崩潰並被服務重新啟動，要在歷史清單找崩潰前的工作階段，並另匯出重啟後的工作階段，不能只交「本次執行」。

### 6.2 從 Pi 匯出診斷 ZIP

1. 插入 USB 隨身碟或 SD 卡讀卡機，確認 Pi 桌面已掛載。首頁進「通訊紀錄」；其他操作頁可用「紀錄」入口。
2. 選取故障所屬的本次／歷史工作階段。
3. 選外接裝置，或選擇 `/media/pi/裝置名稱` 下的資料夾；未出現時按「重新整理」。沒有媒體時可先選 `/home/pi`，稍後由現場人員複製。
4. 按「匯出診斷 ZIP」，等待「已完成並檢查」。檔名為 `PIMEX_debug_時間_識別碼.zip`。
5. 匯出採固定快照，快照之後發生的事件要再次匯出。取消、空間不足、裝置移除等失敗時不可將 `.zip.partial` 當成完成檔。
6. 按「開啟匯出資料夾」，由桌面檔案管理員卸載裝置，完成後再拔除；工程師電腦端解壓確認可讀。

若全螢幕擋住檔案管理員，可在已停止量測、保存資料且匯出完成後，用 Remote shell 執行 `systemctl --user stop pimex.service`，再回桌面卸載。恢復服務方式見 [Connect SOP](CONNECT-SOP.md)。

診斷資料會輪替清理：分段約 20 MiB、合計目標 500 MiB；受到保護的使用中檔案可能暫時超過目標。請及時匯出，不能假設歷史開機紀錄永久保留。斷電或強制結束可能遺失尚未落盤的尾端紀錄。

### 6.3 另外附量測與系統紀錄

診斷 ZIP **不包含量測 CSV，也不包含 systemd journal**。若有量測，另用 Save data／SAVE 匯出相關批次 CSV 與 metadata；原批次 `uart.jsonl` 也保留作比對。它從批次開始記錄，無法取代量測前的連線診斷。

需要服務錯誤資訊時，在 Remote shell 執行以下唯讀收集流程；檔案會寫到新建的報告資料夾：

```sh
(
    set -eu
    mkdir -p /home/pi/PIMEX/debug-reports
    report=$(mktemp -d /home/pi/PIMEX/debug-reports/report.XXXXXX)
    date -Is > "$report/time.txt"
    git -C /home/pi/Photoelectromagnetic-electrochemical log -1 --format=fuller > "$report/software.txt" 2>&1 || true
    git -C /home/pi/Photoelectromagnetic-electrochemical status --short >> "$report/software.txt" 2>&1 || true
    systemctl --user show pimex.service -p MainPID -p ActiveState -p SubState -p NRestarts > "$report/service.txt"
    journalctl _SYSTEMD_USER_UNIT=pimex.service -b --no-pager -n 1000 > "$report/pimex-journal.txt"
    journalctl -k -b --no-pager -n 300 > "$report/kernel-journal.txt" 2>&1 || true
    printf 'REPORT: %s\n' "$report"
)
```

將 `REPORT:` 路徑內檔案一起複製到外接媒體。上述 journal 只涵蓋本次 Pi 開機、指定的最後行數，可能不足以包含早先事件；如已知時間區間，另外使用 `journalctl` 的 `--since`／`--until` 查詢。核心日誌若無權限，記錄無法讀取，不要將空白輸出解讀為沒有 USB 異常。

如果 GUI 已無法匯出，在確認硬體停止後先停止 `pimex.service`，再透過桌面檔案管理員複製 `/home/pi/PIMEX/diagnostics` 中相關的整個 `session_*` 資料夾和上述報告。這是原始診斷，不是標準 ZIP 匯出包；請保持檔案原貌並註明「GUI 無法匯出」。

主板若本來就有 SD 卡／另一個獨立 debug 介面的紀錄，也附上對應時間段與取得方式。不要把 Pi 外接讀卡機、ESP32 自身 SD 卡與 Pi 系統卡視為同一份資料。

## 7. 工程師收到 Log 後的閱讀順序

### 7.1 先確認紀錄是否足夠

先讀 `summary.txt` 與 `manifest.json`：

| 欄位 | 判讀 |
|---|---|
| `session_id`、`started_at`、`snapshot_at` | 是否為正確程式執行階段，是否涵蓋故障時間。 |
| `source_sha256` | Pi 程式碼內容雜湊，**不是 Git commit**；搭配測試表填寫的 commit 與本機異動資訊比對。 |
| `pruned_segments` | 大於 0 代表早期分段已輪替刪除，可能缺少開機或開始事件。 |
| `dropped_records`、`write_failed`、`warning` | 佇列滿或寫入失敗時，不能用「沒有記到」直接判定「主板沒有送」。 |
| `malformed_records` | 匯出時無法解析的診斷 JSON 行數，不是 UART 協定錯誤數；查 `raw/` 原檔。 |
| `clean_shutdown` | 正在執行的工作階段也會是 false，不能單憑此欄認定崩潰。 |

### 7.2 對照事件與收發順序

讀 `events.log` 找開埠、版本、批次與錯誤，再用 `uart.txt` 看可讀收發資料；需要精確程式分析時讀 `uart.jsonl` 或 `raw/records-*.jsonl`。`events.log` 每行也是 JSON。

| 事件 | 代表什麼／不能代表什麼 |
|---|---|
| `serial_open_attempt`／`serial_opened`／`serial_open_failed` | Pi 嘗試開埠、成功或失敗；內含串口參數。 |
| `uart_rx_bytes` | Pi 從串口讀到的一塊原始 bytes，以 `data_hex` 保存；不是一個保證完整的協定封包。 |
| `uart_rx_line` | 已依 LF 分行的文字；非 ASCII 字元可能顯示替代字元，要看 bytes 確認原值。 |
| `firmware_received` | 版本行已被解析，`supported` 表示是否為 028。 |
| `command_requested` | 控制流程提出命令；後續仍可能在保存或傳送階段失敗。不是所有故障停止命令都會有此事件。 |
| `uart_tx_attempt`／`uart_tx_failed` | 串口層嘗試傳送／已辨識的傳送失敗。 |
| `uart_tx_queued` | 查 `accepted_bytes`、`bytes` 與 `complete`；完整排入 Qt 傳送佇列仍不代表主板收到。 |
| `uart_tx_written` | Qt 回報已寫出的位元組數，可能分次通知；不是 ESP32 ACK，也不能只靠次數推算命令數。 |
| `measurement_state`／`response_timeout` | Pi 狀態轉換與等待逾時；先確認卡在 configuring、await_start、running 或 stopping。 |
| `protocol_error`／`uart_framing_error` | 協定錯誤／分行錯誤；仍需檢查原始文字與 bytes。 |
| `board_boot`／`serial_error`／`fault` | 主板開機行、串口錯誤、控制流程故障；依時間判斷先後。 |
| `batch_start`／`batch_end` | 批次 metadata；`batch_end` 也可能是中止或故障，查內部 `state`／`reason`。 |

在同一工作階段，以 `seq` 與 `elapsed_s` 對照先後／間隔；`host_time` 是主機時鐘，校時可能跳動。`elapsed_s` 從該程式啟動起算，不能跨兩次啟動直接相減，也不代表主板的實際發送時間。

RX bytes 與 RX line 是同一份 UART 資料的不同表示，不能重複計為樣本；bytes 的十六進位 `0a` 是 LF，`0d0a` 是 CRLF。版本文字可能分散在多個 RX bytes 事件中；依 `seq` 接合才可判斷完整內容。只有 bytes、沒有 line 時，優先確認是否尚未收到 LF 或發生長度限制錯誤。

`batch_metadata.json` 以批次 ID 索引；若快照還沒包含 `batch_end`，內容可能只是開始時的 metadata，不是最終量測統計。量測批次 `metadata.json` 的 `settings_reply.diagnostics_session` 可對應診斷 `session_id`。

**重播注意：**診斷 ZIP 裡的 `uart.txt` 帶有時間／事件欄位，不是 UI「紀錄重播」的原始 FW 文字格式，不能直接拿來驗收重播。若要製作重播輸入，另從 `uart_rx_line` 的 `line` 欄位依序擷取；不要改寫交付的原始診斷包。

## 8. 常見問題定位表

| 現象 | 優先查什麼 | 下一步 |
|---|---|---|
| 沒有 `serial_opened` | 裝置是否存在、開埠錯誤、dialout 權限、其他程序占用 | 先解決作業系統／USB 層，不先推定版本解析錯誤。 |
| 開埠後沒有 RX bytes | 主板何時發送、供電、USB 列舉、串口選擇；診斷有無缺漏 | 對照主板現有紀錄／獨立量測證據；Pi 無法還原開埠前的訊息。 |
| 有 bytes，沒有版本確認 | LF、原始版本字串、分段接收、亂碼 | 檢查是否實際為 `FW_VERSION: 028`，以及是否需要拼接數個 bytes 事件。 |
| 有 FW 028，Start 仍不可用 | 是否有選孔、舊批次、正在量測、CA 模式或停止狀態未確認 | 保存資料後清除舊批次；依介面提示恢復，不要跳過硬體停止確認。部分選孔會在開始時被拒絕。 |
| 送 APPCFG_RST 後卡住 | 四個設定欄位與 OK 是否齊全、文字格式、8 秒逾時 | 附完整回覆與時間線，指出缺哪一項。 |
| 送 VRE_XSCAN_FUD 後卡住 | 只有 OK 或也有 START；START 是否符合格式 | 查 await_start 逾時；不要手動補送第二次掃描。 |
| 量測中故障 | 未排程座標、無效 XS_FUD、ERROR 類文字、Reset、串口錯誤、30 秒樣本中斷 | 保留第一個 fault 之前的事件；Q 可能是故障後的處置，不能反過來當成起因。 |
| END 後孔位／筆數不對 | 原始座標、各孔 sample counts、欄切換順序 | END 不保證完整；需要主板端對這組參數的預期筆數依據。 |
| Q 已寫出但沒有停止 | TX 佇列／寫出結果、主板是否收到、主板回覆及真實輸出狀態 | 列為停止流程未確認；依硬體方式確認安全狀態，再依第 9 節恢復。 |
| UI 沒顯示重複 FW | `uart_rx_line`／`firmware_received` 是否仍存在 | UI 合併連續重複狀態且只保留最近 500 行，不能以畫面行數當作接收筆數。 |
| 只有 generic 除錯文字也觸發錯誤 | 文字是否含 ERROR／ERR／FAIL／FAILED／BUSY／INVALID | 目前解析器可能將這些詞辨識為錯誤；附原文，區分真實主板錯誤或格式衝突。 |
| ZIP 匯出失敗 | 目的地是否掛載、唯讀、空間、Pi 暫存空間 | Pi 原始紀錄仍保留，換可寫入位置重試；不要提供 partial 檔當成功包。 |

## 9. 異常後恢復到可測狀態

1. 保存故障時的紀錄與畫面；如存檔失敗，先另存量測資料到可寫入位置。
2. 由硬體工程師確認主板已停止，並確認必要的電壓／光源輸出狀態。
3. 若畫面顯示停止狀態未確認，開「連線設定」，按 **「我已確認設備停止 · 清除連線」**。此按鈕是操作者確認，不會替你驗證主板停止。
4. 重新開「連線設定」，選正確串口及 LF／CRLF，按「連接 UART」。若只是首次等待裝置尚未成功連線，則可繼續觀察啟動重試。
5. 重新確認收到 FW 028；是否需要主板 Reset，依第 2 節的上電／USB 行為判斷。
6. 保存原批次後按 CLR all，重新選孔，使用新的測試編號開始。不要把中斷前後資料接成同一次正常量測。

若需重新啟動 Pi 程式，完成上述保存與硬體停止確認後才執行 `systemctl --user restart pimex.service`；新程序是另一個診斷工作階段，不會自動繼續上一批量測。

## 10. 問題回報範本

請將以下內容與附件交給 Pi／ESP32 開發人員；一次回報一個主要問題。

```text
問題編號／測試案例：
操作者／日期時間／時區：
Pi 程式 commit／是否有本機修改：
Pi 診斷 session_id／source_sha256：
主板板號／硬體版本：
FW_VERSION／燒錄檔識別或 firmware commit：
USB 接法／供電方式／Reset 是否造成 USB 重新列舉：
UART 連接埠／送出換行（LF 或 CRLF）：
上電順序與各操作時間：
模式／CV 參數／R G B／完整孔位：
batch_id（未量測填無）：

重現步驟：
1.
2.
3.

預期結果：
實際結果／畫面訊息：
發生次數／測試總次數：
第一個異常事件 seq／elapsed_s：
主板端是否觀察到命令；證據來源：
有無 pruned_segments／dropped_records／write_failed：
已嘗試的恢復方式及結果：

附件：
- 原始診斷 ZIP（如涉及程式重啟，附前後兩次）
- 問題畫面
- 批次 metadata／UART／CSV（如有量測）
- Pi service／journal 報告（如有異常）
- ESP32 原有 Log 或獨立量測證據（如有）
```

結案時分別記錄「通訊流程」、「資料格式與孔位」、「量測數值／筆數」、「實際停止輸出」的結果。軟體測試通過、能開啟串口、有收到 FW 或 END，都不能單獨代替全部實機驗收。

程式行為依據：[UART 傳輸](../instrument_ui/transports.py)、[協定解析](../instrument_ui/protocol.py)、[量測狀態機](../instrument_ui/controller.py)、[診斷匯出](../instrument_ui/diagnostics.py)。
