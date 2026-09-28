# 台中 NAS 部署

部署方式：Synology DS720+／使用者 `edward61221`／SSH Port 50000。Web 使用 HTTP Port 50003，預設 NVIDIA NIM `z-ai/glm-5.3-flash`；模型算力在 NVIDIA 端，NAS 執行 Web、圖片處理、排隊與資料保存。

先在 Mac 完成自動化測試、手機尺寸互動測試與實際 NIM 辨識，再傳送同一版程式到 NAS。NAS 的系統 Python 不更動，使用專案獨立的 Python 3.12 與鎖定依賴。由於目前 SSH 使用者沒有 Docker daemon 權限，本次採原生背景服務。

## 目前版本與發布界線

本地開發版另增加兩行 LINE 分享與 Google AI Studio／Gemini，尚未部署 NAS；仍依本地驗證、使用者接受後再發布的流程進行。Mac 背景服務已依使用者要求關閉，這次測試僅用隔離暫存環境。

截至 2026-09-28，使用者已完成 Mac 手機驗證並同意發布，NAS 的 `current` 已指向 `/volume1/homes/edward61221/nameplate/releases/20260928-identity-e4a62f9`，程式 commit 為 `e4a62f91a773bc4bd74e3dea36819bda6067d40a`。新辨識使用 `nameplate_identity_v002`，只擷取室外機型號、室內機型號、序號；歷史 19 欄與原 `nameplate_v001` 保留。預設仍為 NVIDIA NIM `z-ai/glm-5.3-flash`，`NVIDIA_REASONING_EFFORT` 未設定，不套用低思考量實驗。

本次沿用 NAS 的共享資料，未以 Mac 快照覆寫，沒有資料庫 migration 或依賴變更。已核對新 API 預設三欄、歷史欄位目錄仍有 19 欄，既有 12 筆工作、14 次辨識、9 版人工確認、171 筆欄位標註及 13 筆模型觀測不變；12 張原圖雜湊與 9 版既有分享文字均通過核對，SQLite 完整性正常。備份位於 `backups/20260928-identity-e4a62f9-retry1/`。另以 NAS 既有真實照片在專案外的隔離暫存環境完成一次三欄 NIM 辨識，推論 79.67 秒、3,116 tokens；暫存已清除，正式資料庫未新增測試紀錄或人工答案，詳見 [驗證紀錄](verification.md)。

之前的 `20260928-branding-v2` 是先行發布的名稱修補版，主標題「陳憲隆自製 大金空調銘牌辨識」與小字副標題「AI 智慧影像辨識」沿用。Mac 背景服務目前已關閉；NAS 是正式資料來源，兩台主機的新增資料不會自動同步。

NAS release 透過複製程式檔案部署，裡面沒有 `.git`。GitHub 更新不會自動改變 NAS，不能在 `current` 內用 `git pull` 當成發布流程。

## 目錄

```text
/volume1/homes/edward61221/nameplate/
├── current -> releases/20260928-identity-e4a62f9
├── releases/20260928-nim-review-v1/
├── releases/20260928-branding-v2/
├── releases/20260928-identity-e4a62f9/
├── backups/20260928-identity-e4a62f9-retry1/
├── shared/
│   ├── .env                 # 600；只透過 SSH 傳送
│   ├── data/                # SQLite、原圖、處理圖
│   ├── datasets/
│   └── runtime/             # 程序監督、受保護控制資訊、輪替 log
└── tools/                   # uv、獨立 Python
```

每個 release 的 `.env` 指向 `shared/.env`，資料使用固定共享路徑。更換程式版本不會建立空白資料庫或覆寫照片。不要刪除目前虛擬環境所使用的獨立 Python 目錄。

## 啟停與日常檢查

登入 NAS 後，以固定絕對路徑管理：

```sh
/volume1/homes/edward61221/nameplate/current/.venv/bin/python \
  /volume1/homes/edward61221/nameplate/current/scripts/service.py status \
  --runtime-dir /volume1/homes/edward61221/nameplate/shared/runtime
```

將 `status` 換成 `start`、`stop` 或 `restart` 可管理程序。Supervisor 會監督 Web 與 Worker，任一結束後成組重啟，退避時間最高 30 秒；這是程序恢復，不是自動重試失敗的辨識工作。停止或更新前請先確認沒有正在處理的工作。

Log 位於 `shared/runtime/service.log`，每檔上限 5 MiB、最多 4 檔。`service.py status` 的 RUNNING 表示監督程序已啟動子程序，仍需另外檢查 `/healthz`、登入與 Worker。

## 開機自動啟動

目前背景服務可在 SSH 中斷後繼續運作。使用者回報已在 DSM 設定開機任務，但**尚未以實際 NAS 重開機驗證自動恢復**。SSH 使用者沒有可用的 user systemd／crontab，也沒有免密 Docker 管理權限。

DSM「控制台 → 任務排程」中，該「觸發的任務 → 使用者定義的指令碼」應使用 `edward61221`，事件為「開機」，執行：

```sh
/volume1/homes/edward61221/nameplate/current/.venv/bin/python /volume1/homes/edward61221/nameplate/current/scripts/service.py start --runtime-dir /volume1/homes/edward61221/nameplate/shared/runtime
```

安排可停機的時段重開機後，仍需核對 supervisor、Web／Worker、外部登入與一筆辨識，才算完成開機恢復驗收。

## 網路

NAS 區網位址為 `192.168.0.3`，區網入口為 [NAS 區網網址](http://192.168.0.3:50003/)，外部入口為 [台中 NAS 網址](http://home-taichung.myds.me:50003/)。外部入口需維持 TCP 50003 的路由器轉發及防火牆允許。

2026-09-28 三欄版本發布後，從 Mac 連至外部 DDNS 的 `/healthz` 與 `/login` 均通過，標題與 5 個前端靜態檔案雜湊符合已驗收版本；SSH 中斷後 NAS 服務仍持續運作。這是當次連線結果，後續網路異常仍須分別檢查服務、轉發與防火牆。

`.env` 保留原存取碼，`TRUSTED_HOSTS` 僅加入實際 NAS 名稱、IP、DDNS。前端、API、照片與歷史均需登入。不得把 `.env`、私人照片或資料庫傳入公開程式碼庫。

## 初次資料搬遷

初次搬遷時沿用 Mac 的工作與人工確認資料：先用 SQLite backup API 取得一致性快照，再複製該快照所需的不可變原圖／處理圖與資料集。NAS 路徑重定位前保留資料庫備份，使用 `scripts/relocate_storage.py` 驗證檔案雜湊後，交易式更新三種儲存路徑。AI、人工答案、修正歷程及資料集 manifest 內容不變。

```sh
.venv/bin/python scripts/relocate_storage.py \
  --database /volume1/homes/edward61221/nameplate/shared/data/database.sqlite3 \
  --old-root /Volumes/DATA/DATA/冷氣名牌辨識程式 \
  --new-root /volume1/homes/edward61221/nameplate/shared
```

這是一次性資料快照；兩台主機之後的新增資料不會自動同步。開始使用 NAS 後，應以 NAS 作為正式資料來源，Mac 保留開發／回復用途。

以上路徑重定位是初次搬遷用途；一般程式更新沿用共享目錄，不要再次用 Mac 快照覆寫 NAS 的新資料。

## 開發、測試、發布與回復

1. **Mac 開發與測試**：使用隔離測試資料，執行 Python／前端測試，再用手機尺寸檢查上傳、辨識、三欄校正、確認與分享，並確認舊 19 欄紀錄仍可查看及再確認。實際 NIM 測試記錄模型、Prompt、欄位、token、耗時與正確答案；先由使用者接受本機結果。
2. **建立新 release**：將已接受的程式版本複製到 `releases/<新版本名稱>/`，保留可追溯的 Git commit。排除 `.git`、`.env`、`data`、`datasets`、本機 `.venv` 與測試產物。使用 NAS 既有獨立 Python／uv，依 `uv.lock` 安裝新 release 的環境，讓 `.env` 指向 `shared/.env`，確認資料庫、照片與資料集仍使用 `shared` 的固定路徑。
3. **準備切換**：確認沒有排隊或執行中的工作，備份共享資料的一致性 SQLite 快照及相應照片／資料集，記下 `current` 原目標。保留舊 release 與其 Python 環境。若需要 migration，先確認備份與版本相容性；三欄功能本身不應靠清空資料庫部署。
4. **停止、切換、啟動**：由舊 `current` 執行 `service.py stop`，再將 `current` symlink 切到新 release，由新 `current` 執行 `service.py start`；兩者都指定同一 `shared/runtime`。不在既有 release 上覆寫程式，也不讓兩個 Worker 同時處理同一資料庫。
5. **發布後驗證**：檢查 status、`/healthz`、外部登入、舊原圖與確認版本，以及一筆新辨識。核對實際 Prompt／欄位範圍；若 `.env` 明確設定舊 `PROMPT_VERSION`，僅更新程式預設值不會改變它，須在已接受的發布設定中明確指定 `nameplate_identity_v002`。啟動服務的管理行程也不得殘留舊的設定環境變數；最後以服務 API 與新 Attempt 的設定快照驗證，不能只看 `.env` 檔案。
6. **有問題時回復**：先停止服務並保存發布後新增的資料。若尚未產生新三欄資料，可在確認相容後恢復舊 release 與設定，再啟動及驗證；本次切換過程的自動回復已實際成功。若已產生三欄辨識或人工確認，不能直接切回 `20260928-branding-v2`，因為舊版分享流程假設有完整 19 欄。此時優先保留支援兩種欄位的新程式，將 `PROMPT_VERSION` 改回 `nameplate_v001`，讓後續辨識恢復舊範圍；既有三欄與 19 欄資料仍依各自快照讀取。若程式本身必須退版，需先驗證相容修補或另行規劃資料回復；從備份恢復前務必另存發布後的新資料，不以開發機快照覆寫，也不能只換程式便宣稱回復完成。

日常啟停命令見上節。`current` 更新後，DSM 開機指令仍使用同一固定路徑，無須每次改成具體 release 名稱。後續版本仍先在 Mac 驗證，經使用者接受後再更新 NAS。

NIM 的 token 與免費存取規則見 [用量說明](nim-usage.md)。
