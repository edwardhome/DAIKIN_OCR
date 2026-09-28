# 台中 NAS 部署

部署方式：Synology DS720+／使用者 `edward61221`／SSH Port 50000。Web 使用 HTTP Port 50003，預設 Google AI Studio／Gemini `gemini-flash-latest`；NVIDIA NIM `z-ai/glm-5.3-flash` 仍可手動選用。模型算力在所選供應商端，NAS 執行 Web、圖片處理、排隊與資料保存。

先在 Mac 完成自動化測試、手機尺寸互動測試與實際模型辨識，再傳送同一版程式到 NAS。NAS 的系統 Python 不更動，使用專案獨立的 Python 3.12 與鎖定依賴。由於目前 SSH 使用者沒有 Docker daemon 權限，本次採原生背景服務。

## 目前版本與發布界線

截至 2026-09-28，依使用者要求追加高需求提示後，NAS 的 `current` 已指向 `/volume1/homes/edward61221/nameplate/releases/20260928-gemini-busy-ac563ef`，程式 commit 為 `ac563ef259e0779458dac4416cea463a67cbf762`。NAS 與 Mac 私有 `.env` 沿用已同步的 `VISION_PROVIDER=gemini`、`GEMINI_MODEL=gemini-flash-latest` 與新金鑰，本次沒有變更設定，NIM 仍可選用。Mac 背景服務保持關閉。

新辨識仍使用 `nameplate_identity_v002`，只擷取室外機型號、室內機型號、序號；歷史 19 欄與原 `nameplate_v001` 保留。LINE 分享與複製文字改為人工確認的室外機型號、序號兩行，原圖分享保留。NIM 的 `NVIDIA_REASONING_EFFORT` 仍未設定，不套用低思考量實驗。

本次高需求提示更新將供應商明確回報的 HTTP 503 高需求／過載分類為 `PROVIDER_OVERLOADED`，前端顯示「需求量過高，請更換模型」，提供「更換模型」按鈕跳到重新辨識選單。只有一般 HTTP 503 的既有紀錄則提示「模型服務暫時無法使用，請更換模型」，不補猜高需求原因。不會自動重試或切換供應商；使用者選模型後才建立新的 Attempt，原圖與失敗歷程保留。

本次沿用 NAS 的共享資料，未以 Mac 快照覆寫，沒有資料庫 migration 或依賴變更。已核對 live API 預設 Gemini、NIM 仍可選、新辨識三欄、歷史欄位目錄 19 欄。既有 15 筆工作、17 次辨識、10 版人工確認、174 筆欄位標註與 14 筆模型觀測不變；15 張原圖雜湊一致，10 版確認的分享文字逐筆符合兩行人工答案。備份位於 `backups/20260928-gemini-busy-ac563ef/`，上一版 `20260928-gemini-2099f39` 保留供回復。高需求分類另在 NAS 新環境以隔離模擬 HTTP 回覆驗證，未追加實際模型呼叫。

前次 `20260928-gemini-2099f39` 發布的是兩行分享與 Gemini Provider，當時保留了 13 筆工作、15 次辨識，備份仍位於 `backups/20260928-gemini-2099f39/`。之後 NAS 新增的兩筆工作已納入本次備份，並未由舊快照覆蓋。

前次 Gemini 發布時，新金鑰在 Mac／NAS 查詢模型資訊均回應 HTTP 200；NAS 實照推論的三次檢查皆遇到 Gemini HTTP 503 高需求回覆，因此尚未完成新金鑰的成功實照驗證，用量未知。服務按使用者指定維持 Gemini 預設，忙碌時可稍後重試或手動選 NIM，不會自動切換。先前 NIM 發布與舊金鑰 Gemini 的成功測試不能當作新金鑰實照成功，詳見 [驗證紀錄](verification.md)。

之前的 `20260928-branding-v2` 是先行發布的名稱修補版，主標題「陳憲隆自製 大金空調銘牌辨識」與小字副標題「AI 智慧影像辨識」沿用。Mac 背景服務目前已關閉；NAS 是正式資料來源，兩台主機的新增資料不會自動同步。

NAS release 透過複製程式檔案部署，裡面沒有 `.git`。GitHub 更新不會自動改變 NAS，不能在 `current` 內用 `git pull` 當成發布流程。

## 目錄

```text
/volume1/homes/edward61221/nameplate/
├── current -> releases/20260928-gemini-busy-ac563ef
├── releases/20260928-nim-review-v1/
├── releases/20260928-branding-v2/
├── releases/20260928-identity-e4a62f9/
├── releases/20260928-gemini-2099f39/
├── releases/20260928-gemini-busy-ac563ef/
├── backups/20260928-identity-e4a62f9-retry1/
├── backups/20260928-gemini-2099f39/
├── backups/20260928-gemini-busy-ac563ef/
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

2026-09-28 高需求提示版本發布後，從 Mac 連至外部 DDNS 的 `/healthz` 通過，5 個前端靜態檔案雜湊符合 `ac563ef`，NAS 的 Supervisor、Web 與 Worker 正常運作。前次 Gemini 發布也已驗證外部登入與 SSH 中斷後持續運作。Mac 背景服務維持停止。這是當次連線結果，後續網路異常仍須分別檢查服務、轉發與防火牆。

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

1. **Mac 開發與測試**：使用隔離測試資料，執行 Python／前端測試，再用手機尺寸檢查上傳、辨識、三欄校正、確認與分享，並確認舊 19 欄紀錄仍可查看及再確認。實際模型測試記錄供應商、模型版本、Prompt、欄位、token、耗時；人工答案另行核實，模型輸出不直接當作 Ground Truth。先由使用者接受本機結果。
2. **建立新 release**：將已接受的程式版本複製到 `releases/<新版本名稱>/`，保留可追溯的 Git commit。排除 `.git`、`.env`、`data`、`datasets`、本機 `.venv` 與測試產物。使用 NAS 既有獨立 Python／uv，依 `uv.lock` 安裝新 release 的環境，讓 `.env` 指向 `shared/.env`，確認資料庫、照片與資料集仍使用 `shared` 的固定路徑。
3. **準備切換**：確認沒有排隊或執行中的工作，備份共享資料的一致性 SQLite 快照及相應照片／資料集，記下 `current` 原目標。保留舊 release 與其 Python 環境。若需要 migration，先確認備份與版本相容性；三欄功能本身不應靠清空資料庫部署。
4. **停止、切換、啟動**：由舊 `current` 執行 `service.py stop`，再將 `current` symlink 切到新 release，由新 `current` 執行 `service.py start`；兩者都指定同一 `shared/runtime`。不在既有 release 上覆寫程式，也不讓兩個 Worker 同時處理同一資料庫。
5. **發布後驗證**：檢查 status、`/healthz`、外部登入、舊原圖與確認版本，以及一筆新辨識。核對實際 Prompt／欄位範圍；若 `.env` 明確設定舊 `PROMPT_VERSION`，僅更新程式預設值不會改變它，須在已接受的發布設定中明確指定 `nameplate_identity_v002`。啟動服務的管理行程也不得殘留舊的設定環境變數；最後以服務 API 與新 Attempt 的設定快照驗證，不能只看 `.env` 檔案。
6. **有問題時回復**：若只是本次提示功能有問題，先等待在途工作完成、保存最新共享資料，再停止服務並切回 `20260928-gemini-2099f39`，既有 Gemini 設定可沿用，僅失去本次高需求提示。若問題是 Gemini 供應商，優先保留新版程式、將 `VISION_PROVIDER` 改為 `nvidia`，重啟並確認新工作使用 NIM。若必須退回更早的 `20260928-identity-e4a62f9`，需先完成 Gemini 工作、恢復 NIM 設定；該版本可讀取已完成的 Gemini 三欄結果與人工確認，但不會執行 Gemini 佇列、Gemini tokens 會顯示未知，分享文字也會回到舊格式。不要以發布前的資料庫覆蓋後續新增資料。`20260928-branding-v2` 假設完整 19 欄，不可直接拿來讀取新的三欄資料；需要額外相容修補與驗證。

日常啟停命令見上節。`current` 更新後，DSM 開機指令仍使用同一固定路徑，無須每次改成具體 release 名稱。後續版本仍先在 Mac 驗證，經使用者接受後再更新 NAS。

NIM 的 token 與免費存取規則見 [用量說明](nim-usage.md)。
