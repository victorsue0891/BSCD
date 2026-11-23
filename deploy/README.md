# Raspberry Pi 部署與維護流程

**目前只能用 Raspberry Pi Connect 連線時，請使用 [Connect 部署 SOP](CONNECT-SOP.md)**：由 Pi 從公開 GitHub 下載、測試、備份替換及還原，不需要 SSH／SCP。下文保留原本區域網路部署流程。

本文件依 2026-11-03 實際部署流程整理，於 2026-11-04 補齊可重複操作的步驟。實際傳輸透過 SSH／SFTP；下方使用 Windows 內建 `ssh`、`scp` 與 `tar` 示範相同步驟，不需要另裝部署用 Python 套件。

公開版本以 `raspberrypi.local` 取代現場連線位址；執行 SSH／SCP 前請換成你的 Pi IP 或主機名稱。以下本機與 Pi 安裝路徑亦請依環境調整。

## 部署目標與結果

| 項目 | 本次設定 |
|---|---|
| Raspberry Pi 連線位址（示例） | `raspberrypi.local`；請替換成實際 IP／主機名稱 |
| 登入帳號 | `pi`；密碼在 SSH 提示時輸入，不存入文件或服務 |
| 作業系統／架構 | Debian GNU/Linux 13（trixie）／ARM64（`aarch64`） |
| 圖形桌面 | LightDM 自動登入 `pi`，labwc／Wayland |
| 實際螢幕 | 1024×600；程式使用 `--fullscreen` 填滿畫面 |
| 程式路徑 | `/home/pi/Photoelectromagnetic-electrochemical` |
| 量測資料 | `/home/pi/PIMEX/data` |
| ESP32 串口 | `/dev/ttyACM0`；115200、8N1、無流量控制、LF |
| 開機服務 | `pi` 的 systemd 使用者服務 `pimex.service` |

部署時 Windows 與 Pi 均通過 29 項測試；重新開機後服務自動啟動，並以實際螢幕截圖確認全螢幕首頁。串口成功開啟，但當時尚未收到 `FW_VERSION: 028`，因此未宣稱已完成實機量測驗收。

## 1. 連線與檢查環境

在 Windows PowerShell 執行：

```powershell
ssh pi@raspberrypi.local
```

登入 Pi 後執行：

```sh
hostname
cat /etc/os-release
uname -m
id
systemctl get-default
systemctl status display-manager --no-pager
loginctl list-sessions
ls -l /dev/ttyACM0
ls -l /dev/serial/by-id/
```

本次已具備桌面環境、自動登入及 `dialout` 群組權限，無須修改。若在另一台新裝 Pi 重做部署，需使用含圖形桌面的系統，透過 `sudo raspi-config` 設定桌面自動登入 `pi`；缺少串口群組時執行：

```sh
sudo usermod -aG dialout pi
```

新增群組後需重新登入或重新開機，讓桌面與使用者服務取得新權限。

## 2. 安裝執行與驗證套件

在 Pi 執行：

```sh
sudo apt-get update
sudo apt-get install -y python3-pyqt6 python3-pyqt6.qtserialport qt6-wayland fonts-noto-cjk python3-pytest grim
python3 -c 'from PyQt6.QtCore import PYQT_VERSION_STR; from PyQt6.QtSerialPort import QSerialPort; print(PYQT_VERSION_STR)'
```

`python3-pyqt6` 與 QtSerialPort 提供 GUI 及串口功能；`qt6-wayland` 支援本機桌面，`fonts-noto-cjk` 提供中文字型。`python3-pytest` 用於驗證；`grim` 用於 Wayland 畫面截圖。本次 Pi 使用系統 Python 與 apt 套件，沒有複製 Windows 的 `.venv`。

## 3. 打包並傳輸專案

另開 Windows PowerShell，在本機專案目錄執行。封裝明確列出的程式、資產、部署設定、測試與重播資料：

```powershell
Set-Location D:\test\Photoelectromagnetic-electrochemical
$pimexArchive = Join-Path $env:TEMP 'pimex-deploy.tar.gz'
tar -czf $pimexArchive --exclude=__pycache__ main.py README.md requirements.txt requirements-dev.txt start_pi.sh RefTxt1006.txt instrument_ui tests deploy
tar -tzf $pimexArchive
scp $pimexArchive pi@raspberrypi.local:/home/pi/pimex-deploy.tar.gz
```

封裝內容不包含 Windows 虛擬環境、舊 `release/` 副本或工作用 `artifacts/`。務必保留 `instrument_ui/assets/`，否則首頁背景及 Logo 無法正常顯示。

以下為 **首次安裝** 的解壓指令，在 Pi 執行。若目的目錄已存在，指令會停止；請改依後面的「更新已部署版本」處理。

```sh
(
    set -eu
    project=/home/pi/Photoelectromagnetic-electrochemical
    test ! -e "$project"
    mkdir -p "$project"
    tar -xzf /home/pi/pimex-deploy.tar.gz -C "$project"
)
```

## 4. 驗證程式

在 Pi 專案目錄執行：

```sh
cd /home/pi/Photoelectromagnetic-electrochemical
python3 -m pytest -q
python3 main.py --help
```

本次結果為 `29 passed`。測試以 offscreen 模式驗證 UI，不需要從 SSH 開啟可見視窗。部署過程亦修正模擬器的延遲回呼生命週期問題，避免物件釋放後仍收到回呼而導致程式退出。

若要手動體驗模擬，在 **Pi 本機圖形桌面的終端機**執行：

```sh
python3 main.py --demo --fullscreen
```

關閉模擬視窗後，可手動啟動實機連線模式：

```sh
python3 main.py --fullscreen --port /dev/ttyACM0 --line-ending LF
```

服務已啟動時，先在介面停止量測並確認完成，再執行 `systemctl --user stop pimex.service`，避免同時啟動兩份程式搶占串口。

## 5. 安裝開機服務

以 `pi` 身分執行下列指令；`systemctl --user` 不加 `sudo`：

```sh
cd /home/pi/Photoelectromagnetic-electrochemical
mkdir -p ~/.config/systemd/user ~/.config/autostart ~/PIMEX/data
install -m 644 deploy/pimex.service ~/.config/systemd/user/pimex.service
install -m 644 deploy/pimex.desktop ~/.config/autostart/pimex.desktop
systemd-analyze --user verify ~/.config/systemd/user/pimex.service
systemctl --user daemon-reload
systemctl --user enable pimex.service
```

三個部署檔案各有用途：

| 檔案 | 用途 |
|---|---|
| [pimex.service](pimex.service) | systemd 管理程式，帶入全螢幕、串口、換行格式及資料目錄；退出後 5 秒重新啟動，60 秒內最多嘗試啟動 5 次 |
| [pimex.desktop](pimex.desktop) | 放入 `~/.config/autostart/`，由桌面登入流程呼叫啟動腳本 |
| [start-session.sh](start-session.sh) | 匯入桌面顯示環境，再呼叫 `systemctl --user start pimex.service` |

這台 Pi 的 labwc 沒有自動啟動 `graphical-session.target`，所以僅執行 `systemctl --user enable` 不足以保證 GUI 開機啟動，還需要安裝上述桌面自動啟動入口。實際順序是：**開機 → LightDM 自動登入 pi → labwc 桌面就緒 → XDG autostart → systemd 啟動 PIMEX**。

在 **Pi 本機圖形桌面的終端機**可立即啟動：

```sh
sh /home/pi/Photoelectromagnetic-electrochemical/deploy/start-session.sh
```

若從 **SSH** 操作，先檢查使用者服務管理器已有桌面環境：

```sh
systemctl --user show-environment
```

本次可看到 `XDG_SESSION_TYPE=wayland`、`WAYLAND_DISPLAY=wayland-0`、`XDG_RUNTIME_DIR=/run/user/1000`，因此直接執行：

```sh
systemctl --user start pimex.service
```

若桌面尚未登入或沒有顯示環境，先讓 Pi 完成桌面登入，由自動啟動入口處理；不要將 SSH 轉送的 `DISPLAY` 匯入服務環境。

## 6. 重新開機驗證

確認沒有進行中的量測後，在 Pi 執行：

```sh
sudo reboot
```

等待 Pi 完成桌面登入，再從 Windows 使用 `ssh pi@raspberrypi.local` 重新連線。在 Pi 執行：

```sh
systemctl --user is-enabled pimex.service
systemctl --user status pimex.service --no-pager
systemctl --user show pimex.service -p ActiveState -p SubState -p MainPID -p NRestarts
journalctl _SYSTEMD_USER_UNIT=pimex.service -b --no-pager -n 30
fuser -v /dev/ttyACM0
```

本次重新開機後確認為 `enabled`、`active (running)`、`NRestarts=0`，日誌出現「UART 已連線：/dev/ttyACM0」。SSH 比桌面較早就緒時，服務可能短暫顯示 `inactive`；應待桌面登入完成再檢查。

本機螢幕應直接顯示 PIMEX 全螢幕首頁。這台 Pi 也可透過 SSH 擷取桌面驗證：

```sh
WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000 grim /home/pi/pimex-service.png
```

再於 Windows 下載圖片：

```powershell
scp pi@raspberrypi.local:/home/pi/pimex-service.png .\pimex-service.png
```

上面的 `wayland-0` 與 UID `1000` 是本次環境值；其他設備請依 `systemctl --user show-environment` 的實際值調整。本次另比對部署檔案的 SHA256，確認當時本機與 Pi 的 27 個封裝檔案一致；後續新增文件會改變檔案數量。

## 串口與量測狀態

ESP32 工程師進行整合測試時，請依 [測試與 Debug SOP](ESP32-DEBUG-SOP.md) 執行並保存診斷包。

`--port /dev/ttyACM0` 啟動時會自動開啟串口。若 USB 尚未出現，每 2 秒重試；使用者可由連線設定切換。首次連線成功後再發生斷線，須手動處理，不會自動恢復量測。

服務啟動只會開啟操作介面及串口，仍需使用者選取參數、孔位並按 Start。實機 CV 要先收到 `FW_VERSION: 028`；若錯過 ESP32 開機訊息，可保持程式連線並重新啟動 ESP32，確認韌體回覆後再量測。LF／CRLF 仍需依實機確認；CA 實機流程尚未啟用，詳見主 [README](../README.md)。

## 日常管理與版本更新

### 2026-11-23 新增診斷紀錄與外接儲存匯出

此節說明本次程式修改的使用方式；前述 2026-11-03 的部署驗證結果不代表新版已部署或完成實機驗收。更新程式後，既有 service 的 `--data-dir /home/pi/PIMEX/data` 會自動對應診斷目錄 `/home/pi/PIMEX/diagnostics`，無須新增套件或變更 ESP32 韌體。若要指定其他本機位置，可在 service 的 `ExecStart` 加上 `--diagnostics-dir /指定/目錄`，並在重新安裝 service 後執行 `systemctl --user daemon-reload`。

診斷從程式啟動即開始，不必開啟「通訊紀錄」，也不必先量測。首頁及量測頁區分「串口已開啟／等待主板版本」與「已收到 FW 028」；收到版本不會回傳新的確認指令。版本只在串口開啟前送出一次時，仍須保持連線後重新啟動主板。不要在進行量測時重新啟動主板。

取出工程師需要的 Log：

1. 插入 USB 或 SD 卡讀卡機，確認桌面已掛載。可在 Pi 終端機用 `lsblk -o NAME,FSTYPE,LABEL,MOUNTPOINTS` 查看；常見掛載位置為 `/media/pi/裝置名稱`。
2. 在首頁「通訊紀錄」選取本次／歷史紀錄，再選掛載裝置或資料夾，按「匯出診斷 ZIP」。裝置尚未出現時按「重新整理」。
3. 等待「已完成並檢查」；取得 `PIMEX_debug_時間_識別碼.zip`。匯出可取消；拔除、唯讀或空間不足會顯示失敗，不會刪除 Pi 來源。過程中的 `.zip.partial` 不是完成檔案。
4. 按「開啟匯出資料夾」，由桌面檔案管理員卸載裝置，再取出交給工程師。匯出程式不會自動卸載。

ZIP 包含 `summary.txt`、`manifest.json`、`uart.txt`、`uart.jsonl`、`events.log`、`batch_metadata.json` 與 `raw/`。請一併提供整個 ZIP，先由摘要確認是否發生輪替或紀錄缺漏。匯出是固定時間快照，之後發生的故障需再匯出一次；原始量測 CSV 另依「Save data」流程取得。完整格式與限制見主 [README 的診斷說明](../README.md#連線診斷與-usbsd-卡匯出)。

若需暫時回桌面，可使用桌面的切換視窗功能；若全螢幕遮擋操作，也可先完成停止量測與資料保存，再透過 SSH 執行 `systemctl --user stop pimex.service`，使用 Pi 檔案管理員卸載。完成後以 `systemctl --user start pimex.service` 恢復介面。

診斷目錄使用背景寫入與輪替，分段約 20 MiB，目標上限合計 500 MiB；匯出中的分段暫時不刪除，且不會清除 `/home/pi/PIMEX/data`。請保留 Pi 暫存與外接裝置空間。出現診斷寫入失敗時先修復空間／權限，再於安全停止量測後重啟服務。異常斷電或強制停止可能損失尾端紀錄；`clean_shutdown=false` 也可能代表目前仍在執行，不可單憑此欄認定崩潰。

更新驗證時，應先執行完整 pytest，再確認下列實機行為：等待 FW 時 Start 不可用、收到 FW 028 後可用、重複 FW 不送額外命令、USB 匯出成功且可在另一台電腦解壓、匯出失敗會顯示錯誤並保留來源。先在停止量測或模擬模式驗證儲存裝置異常情境，再驗證正式量測；本機測試中的裝置移除屬於故障注入，並非實際 USB 拔插驗證。

### 服務管理與更新

常用管理指令（以 `pi` 執行）：

```sh
systemctl --user status pimex.service
journalctl _SYSTEMD_USER_UNIT=pimex.service -b
systemctl --user stop pimex.service
systemctl --user start pimex.service
systemctl --user restart pimex.service
```

重啟或停止服務前，先在介面完成停止量測與資料儲存。正常關閉程式視窗會依服務設定重新啟動；需保持關閉時使用 `systemctl --user stop`。

更新已部署版本時，先按第 3 步傳送新的壓縮檔，停止服務，將原程式目錄另行備份後再解壓到原路徑。量測資料位於獨立的 `/home/pi/PIMEX/data`，更新時保留此目錄。執行 `python3 -m pytest -q` 成功後才啟動服務；若修改 `deploy/` 的 service 或 desktop 檔案，需重新複製安裝並執行 `systemctl --user daemon-reload`。

永久停用開機啟動，需要同時停用服務與桌面入口：

```sh
systemctl --user disable --now pimex.service
mv ~/.config/autostart/pimex.desktop ~/.config/autostart/pimex.desktop.disabled
```

本次設定檔以帳號 `pi` 與既定安裝目錄為前提。若變更帳號或安裝路徑，請同步調整 `pimex.desktop` 的絕對路徑，以及 `pimex.service` 的 `WorkingDirectory`、`ExecStart`。
