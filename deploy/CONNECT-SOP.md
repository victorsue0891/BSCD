# 透過 Raspberry Pi Connect 更新 BSCD：操作 SOP

適用於目前這台已安裝 PIMEX 的 Raspberry Pi：帳號 `pi`、Wayland 桌面、程式路徑 `/home/pi/Photoelectromagnetic-electrochemical`、使用者服務 `pimex.service`、ESP32 `/dev/ttyACM0`。本文件提供操作流程，並不表示已替遠端 Pi 執行更新。

全程透過 Connect 操作 Pi，由 **Pi 自己從公開 GitHub repository 下載程式**，不需要 Windows SSH／SCP，也不需要在 Pi 登入 GitHub 或安裝 gh CLI。Pi 仍須能連上 GitHub 與 apt 套件來源。

流程：**確認量測停止 → 停止服務 → 安裝套件 → 下載並測試 → 備份與替換 → 啟動與驗證**。每個指令區塊依序執行；發生錯誤就停在該步，不要繼續貼下一步。括號包住的區塊請完整貼上，`set -eu` 會在失敗時停止該區塊。

## 1. 連進 Pi，確認操作位置

1. 在電腦瀏覽器開啟 [Raspberry Pi Connect](https://connect.raspberrypi.com/)，登入原有 Raspberry Pi ID。
2. 選這台 Pi，在 **Connect via → Remote shell** 開啟命令列。
3. 另開 **Screen sharing**，用來停止量測、檢查介面及必要時開啟桌面終端機。若只有 Screen sharing，也可在 Pi 桌面開 Terminal 執行下列命令。

Connect 的 Remote shell 是新的命令列登入；Screen sharing 分享 Pi 已登入的桌面。以下指令全部在 **Pi 的終端機** 執行，不是在 Windows PowerShell。官方操作說明：[Raspberry Pi Connect 文件](https://www.raspberrypi.com/documentation/services/connect.html)。

```sh
whoami
hostname
cat /etc/os-release
df -h /home/pi
ls -ld /home/pi/Photoelectromagnetic-electrochemical
systemctl --user cat pimex.service
```

確認 `whoami` 為 `pi`，舊程式目錄存在，服務指向上述程式路徑。需要能同時存放新版、舊版備份及測試暫存的空間；空間不足請先處理，不要刪除量測資料。若使用者或路徑不同，先調整部署設定，不能直接套用本 SOP。

## 2. 停止量測與服務

先在 Screen sharing 的 PIMEX 畫面按 Stop，等待量測停止／資料保存完成，並確認沒有正在匯出的工作。如果停止狀態不明，先確認主板已停止，再更新。

回 Remote shell 執行：

```sh
systemctl --user stop pimex.service
systemctl --user is-active pimex.service
```

應顯示 `inactive`；此查詢在服務停止時回傳非零狀態是正常現象。PIMEX 關閉後會露出桌面，Connect 本身應繼續運作。若有另外手動開啟的 PIMEX，也要關閉；不要同時開兩份程式搶占串口。

`systemctl --user` 一律以 `pi` 執行，**不要加 sudo**。此次更新不需關閉 Connect、重新啟動顯示管理員或變更 Wayland 設定。

## 3. 安裝必要套件，建立持續操作的終端工作階段

```sh
(
    set -eu
    sudo apt-get update
    sudo apt-get install -y git tmux python3-pyqt6 python3-pyqt6.qtserialport qt6-wayland fonts-noto-cjk python3-pytest
    python3 -c 'from PyQt6.QtCore import PYQT_VERSION_STR; from PyQt6.QtSerialPort import QSerialPort; print(PYQT_VERSION_STR)'
)
```

sudo 若要求密碼，輸入 Pi 帳號密碼；畫面不顯示輸入字元是正常的。使用系統 Python／apt 套件，不複製 Windows `.venv`。

接著執行：

```sh
tmux new-session -A -s bscd-deploy
```

後續步驟在這個 tmux 視窗進行。若瀏覽器斷線，重新開 Connect Remote shell，再執行同一個 tmux 指令回到原工作階段，確認原命令是否已完成；不要重複啟動同一步。tmux 可保留命令列程序，但不能防止 Pi 斷電或重新開機。

## 4. 從 GitHub 下載新版，先測試

舊安裝可能沒有 `.git`，因此不要直接在舊目錄執行 `git pull`。以下每次建立新的候選目錄，通過測試才記錄為可安裝版本：

```sh
(
    set -eu
    test "$(id -un)" = pi
    mkdir -p /home/pi/PIMEX
    candidate=$(mktemp -d /home/pi/BSCD-candidate.XXXXXX)
    git clone --branch main --single-branch https://github.com/victorsue0891/BSCD.git "$candidate"
    cd "$candidate"
    git log -1 --format='%h %s'
    QT_QPA_PLATFORM=offscreen python3 -m pytest -q
    python3 main.py --help
    printf '%s\n' "$candidate" > /home/pi/PIMEX/deploy-candidate-path.txt
    printf 'TESTED CANDIDATE: %s\n' "$candidate"
)
```

目前程式有 **40 項測試**；預期全部通過，最後看到 `TESTED CANDIDATE:`。後續版本測試數可能增加。此測試使用離屏 UI，不會開啟真實 ESP32 串口。公開 repository 正常 clone 不需 GitHub 帳密；若下載或測試失敗，不要繼續替換。

只有這一步成功後才做第 5 步。若此時決定暫緩，舊目錄尚未變更，可依第 6 步啟動舊服務。

## 5. 備份舊版，再替換程式及服務設定

本 SOP 保持原安裝目錄名稱，即使 GitHub repository 名稱是 BSCD，也不要改成 `/home/pi/BSCD`，否則既有 service／桌面入口會找不到程式。

下列區塊要求既有 service 與桌面入口存在。它會保留原本實際安裝的設定，將舊程式移入唯一備份目錄，再安裝通過測試的新版。若你曾手動修改 service 的啟動參數或設定 drop-in，先比較 `systemctl --user cat pimex.service` 與新版 `deploy/pimex.service`，保留需要的客製設定；此處安裝的是 repository 預設值。

```sh
(
    set -eu
    test "$(id -un)" = pi
    project=/home/pi/Photoelectromagnetic-electrochemical
    candidate=$(cat /home/pi/PIMEX/deploy-candidate-path.txt)
    case "$candidate" in /home/pi/BSCD-candidate.*) ;; *) exit 1 ;; esac
    test -d "$project"
    test ! -L "$project"
    test -f "$candidate/main.py"
    test -f /home/pi/.config/systemd/user/pimex.service
    test -f /home/pi/.config/autostart/pimex.desktop
    cd /home/pi
    systemctl --user stop pimex.service
    mkdir -p /home/pi/PIMEX/deploy-backups
    backup=$(mktemp -d /home/pi/PIMEX/deploy-backups/backup.XXXXXX)
    cp -p /home/pi/.config/systemd/user/pimex.service "$backup/pimex.service"
    cp -p /home/pi/.config/autostart/pimex.desktop "$backup/pimex.desktop"
    printf '%s\n' "$backup" > /home/pi/PIMEX/deploy-backup-path.txt
    mv "$project" "$backup/project"
    mv "$candidate" "$project"
    install -m 644 "$project/deploy/pimex.service" /home/pi/.config/systemd/user/pimex.service
    install -m 644 "$project/deploy/pimex.desktop" /home/pi/.config/autostart/pimex.desktop
    systemctl --user daemon-reload
    systemd-analyze --user verify /home/pi/.config/systemd/user/pimex.service
    systemctl --user enable pimex.service
    git -C "$project" rev-parse HEAD > /home/pi/PIMEX/deployed-commit.txt
    printf 'INSTALLED. BACKUP: %s\n' "$backup"
)
```

看到 `INSTALLED. BACKUP:` 才進下一步；如替換中途失敗，依第 9 節還原。量測資料 `/home/pi/PIMEX/data` 與診斷紀錄 `/home/pi/PIMEX/diagnostics` 不會移動或刪除。備份只涵蓋程式與上述兩份設定，不包含 apt 套件或系統設定的還原。

## 6. 啟動全螢幕服務

先在 Remote shell 檢查服務管理器的顯示環境：

```sh
systemctl --user show-environment
```

如果已經有 Pi 桌面對應的 `WAYLAND_DISPLAY` 與 `XDG_RUNTIME_DIR`，執行：

```sh
(
    set -eu
    systemctl --user reset-failed pimex.service
    systemctl --user start pimex.service
)
```

**如果沒有桌面顯示環境：**切到 **Screen sharing → Pi 桌面 → Terminal**，在那裡執行：

```sh
systemctl --user reset-failed pimex.service
sh /home/pi/Photoelectromagnetic-electrochemical/deploy/start-session.sh
```

不要在 Connect Remote shell 或其 tmux 視窗執行 `start-session.sh` 來匯入桌面環境；它們可能只有命令列環境，會帶入錯誤的工作階段資訊。也不要直接在 Remote shell 跑 `python3 main.py --fullscreen`。畫面需要已登入的 Pi 桌面。

## 7. 驗證更新成功

Remote shell 執行：

```sh
systemctl --user is-enabled pimex.service
systemctl --user status pimex.service --no-pager
systemctl --user show pimex.service -p ActiveState -p SubState -p NRestarts
journalctl _SYSTEMD_USER_UNIT=pimex.service -b --no-pager -n 60
git -C /home/pi/Photoelectromagnetic-electrochemical log -1 --oneline
ls -l /dev/ttyACM0
```

確認 `enabled`、`active (running)`，且稍後再查時 `NRestarts` 沒有持續增加。`git log` 的 commit 應與第 4 步下載版本相同；只有 active 不代表串口與量測已驗收。

在 Screen sharing 確認：

- PIMEX 全螢幕首頁可見，按鈕可操作。
- 尚未收到版本時顯示「等待主板版本」；收到 `FW_VERSION: 028` 才允許開始實機 CV。主板若在 Pi 開啟串口之前只送過一次版本，仍需在確認沒有量測後重新啟動主板；此次更新沒有加入 ACK 或版本查詢指令。
- 開啟「通訊紀錄」可見本次／歷史紀錄及匯出功能。沒有 USB 時，可先選 `/home/pi` 測試 ZIP 匯出；正式 USB／SD 卡驗收需裝置實際插入並掛載。
- 實機串口與量測仍需現場確認。這次更新不會自動開始量測，也不啟用 CA 實機流程。

## 8. 開機自動啟動驗證（安排可恢復連線的時段）

更新本身**不需要立即重新開機**。服務與介面已驗證後，再確認 Pi 保留桌面自動登入，且 Connect 會在開機後恢復；目前只有 Connect 可連線時，先確保無法重連時有人能到現場處理。Connect 分享既有桌面，服務的 `enable` 並不會替你登入桌面。

確認沒有量測或匯出進行中，再執行：

```sh
sudo reboot
```

Connect 會暫時斷線。等待裝置重新上線，再開 Remote shell 與 Screen sharing，重做第 7 步。應自動出現全螢幕首頁。若裝置沒有回到 Connect，需先排查 Pi 的電源、網路、Connect 登入與桌面自動登入，不能靠這份程式的服務設定修復連線。

## 9. 新版有問題時還原

若只是第 4 步下載／測試失敗，舊程式尚未替換，直接依第 6 步恢復服務即可。

若已做第 5 步，先完成停止量測及保存資料，再執行以下區塊。它會把新版另存到 `failed.*` 目錄，再把舊版搬回；不刪除新舊程式或量測資料。**還原只執行一次**，因為成功後備份裡的 `project` 已移回正式位置。

```sh
(
    set -eu
    test "$(id -un)" = pi
    project=/home/pi/Photoelectromagnetic-electrochemical
    backup=$(cat /home/pi/PIMEX/deploy-backup-path.txt)
    case "$backup" in /home/pi/PIMEX/deploy-backups/backup.*) ;; *) exit 1 ;; esac
    test -d "$backup/project"
    test -f "$backup/pimex.service"
    test -f "$backup/pimex.desktop"
    cd /home/pi
    systemctl --user stop pimex.service
    failed=$(mktemp -d /home/pi/PIMEX/deploy-backups/failed.XXXXXX)
    if test -e "$project"; then
        mv "$project" "$failed/project"
    fi
    mv "$backup/project" "$project"
    install -m 644 "$backup/pimex.service" /home/pi/.config/systemd/user/pimex.service
    install -m 644 "$backup/pimex.desktop" /home/pi/.config/autostart/pimex.desktop
    systemctl --user daemon-reload
    systemctl --user enable pimex.service
    systemctl --user reset-failed pimex.service
    printf 'RESTORED FROM: %s\n' "$backup" > /home/pi/PIMEX/deployed-commit.txt
    printf 'RESTORED. FAILED VERSION: %s\n' "$failed"
)
```

看到 `RESTORED` 後，依第 6 步啟動、第 7 步檢查。舊版可能不是 Git repository，此時 `git log` 失敗是預期現象。若 `test -d "$backup/project"` 失敗，先查看正式目錄與備份目錄，可能尚未移走舊版或已完成還原；不要猜路徑繼續搬動。

## 常見狀況

| 狀況 | 處理方式 |
|---|---|
| 全螢幕遮住桌面 | 確認量測停止後，從 Remote shell 停止 `pimex.service`，再回 Screen sharing 操作桌面。 |
| `Failed to connect to bus` | 確認 Remote shell 是 `pi`，未使用 `sudo systemctl --user`；改由 Screen sharing 的桌面 Terminal 操作。 |
| `could not connect to display` 或 Wayland 平台錯誤 | 確認已登入桌面、已安裝 `qt6-wayland`，依第 6 步從桌面 Terminal 匯入環境。 |
| `/dev/ttyACM0` 不存在 | 檢查 ESP32 電源與 USB；程式會等待串口出現，但不能因此認定硬體已連線。 |
| 串口 Permission denied | 執行 `id -nG pi` 確認 `dialout`；缺少時以 `sudo usermod -aG dialout pi` 加入，安排重新登入／開機讓桌面取得權限。 |
| 服務不斷重啟 | 先 `systemctl --user stop pimex.service`，讀取 journal；必要時依第 9 節還原。 |
| 瀏覽器中斷 | 重連後執行 `tmux new-session -A -s bscd-deploy`；檢查原操作結果再繼續。 |
| GitHub／apt 連不上 | 檢查 Pi 的對外網路、DNS 與時間；Connect 可連線不代表 GitHub 或套件來源一定可達。 |

後續每次更新可重用第 2～7 步，每次保留當時的舊版。已驗證且不再需要的備份由操作者自行整理；不要將 `/home/pi/PIMEX/data` 或 `/home/pi/PIMEX/diagnostics` 當成程式暫存刪除。
