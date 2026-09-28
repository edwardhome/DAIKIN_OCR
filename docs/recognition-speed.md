# 辨識速度改善

更新日期：2026-09-28。使用者完成 Mac 手機驗證後，三欄版本已部署 NAS，release 為 `20260928-identity-e4a62f9`（程式 commit `e4a62f9`）。新辨識只擷取室外機型號、室內機型號、序號，使用 `nameplate_identity_v002`；歷史 19 欄結果、人工版本與原 `nameplate_v001` 保留。NVIDIA NIM 模型仍是 `z-ai/glm-5.3-flash`，未啟用低思考量預設。

## 已做的改變與單次實測

優先減少要讀取及生成的欄位，維持每次 Attempt 選定一個模型。目前預設為 NVIDIA NIM `z-ai/glm-5.3-flash`，`MODEL_MAX_TOKENS=4096` 保留。另以三張使用者提供的真實照片，做完整圖及兩次有上限的改善實驗，沒有將照片複製進專案或 Git。

| 真實照片／方法 | 模型呼叫 | 總 tokens | 觀察 |
| --- | ---: | ---: | --- |
| A：偏暗室外銘牌，完整圖 | 59.36 秒 | 3,109 | 三欄均回傳，待人工核實 |
| B：室內銘牌，完整圖 | 46.89 秒 | 7,238 | 室外型號保持 null，但室內型號多讀一個字母 |
| B：人工選定區域重讀 | 42.76 秒 | 3,236 | 重複字母問題改善；此區域包含兩處型號印字、序號及室內機上下文 |
| C：斜拍銘牌，完整圖 | 180.11 秒 | 未回報 | 逾時，不能將用量當作 0 |
| C：相同完整圖，`reasoning_effort=low` | 37.32 秒 | 2,754 | API 正常完成，但兩個型號仍有字元錯誤，不採作預設 |

表中每列只有一次請求，B 的重讀與 C 的重試是額外成本，不取代第一次請求的耗時或用量。成功回覆合計 16,337 tokens，逾時請求的用量未知。這些結果**不是平均延遲、固定加速比例或現場正確率**；託管端點負載與網路條件也可能影響結果，尚未建立人工 Ground Truth。

裁切降低了這張照片的輸入負擔，但並沒有使時間等比例縮短；降低思考量也不能只看速度，必須同時核對型號字元。三欄流程雖已經使用者手機驗證並部署，這不代表上述試驗照片已有人工 Ground Truth，也不因 JSON 成功就認定辨識正確。歷史與詳細驗證見 [驗證紀錄](verification.md)。

## 後續實驗順序

### 1. 持續量測三欄流程

使用固定照片確認兩個型號不對調、序號字符完整、未印的欄位保持 null；同時核對人工修改、分享、歷史 19 欄與資料匯出。每輪保留同圖、模型、Prompt、圖片尺寸與 token／耗時紀錄，只改一個條件。速度與三欄 exact match 要一起看，不能只選最快的一次。新舊評分依 [共同欄位規則](benchmark.md) 比較。

### 2. 較低思考量已可設定，正式服務尚未套用

NVIDIA 的 GLM-5.3-Flash 模型文件明確列出 `reasoning_effort` 可用 `low`、`high`、`max`，省略時為 `max`。[NVIDIA 模型文件](https://docs.api.nvidia.com/nim/reference/z-ai-glm-5-3-flash)

程式新增 `NVIDIA_REASONING_EFFORT`，預設空白，只有明確設定才送出參數。TOML profile 也可獨立設定 `reasoning_effort`，並隨辨識設定快照保存。上述單次 `low` 實驗使用獨立測試設定，未變更 Mac 或 NAS 的預設；結果顯示不能僅因回應變快就部署。更換模型時應先確認該端點支援此參數。

原廠說明這個模型的思考不能關閉；不可假定 `enable_thinking: false` 有效。`clear_thinking` 控制歷史思考是否保留，也不是關閉本次思考。[Z.ai 模型說明](https://docs.z.ai/guides/vlm/glm-5.3-flash)、[原廠 chat template](https://huggingface.co/zai-org/GLM-5.3-Flash/raw/main/chat_template.jinja)

vLLM 配方支援頂層 `reasoning_effort` 或 `chat_template_kwargs.reasoning_effort`。NVIDIA 模型介紹有此參數，但該端點的請求參數表未列出；本次頂層 `low` 請求已實際取得 HTTP 200 與完整 JSON，這仍不能證明辨識品質足以取代原設定。[vLLM 官方配方](https://recipes.vllm.ai/zai-org/GLM-5.3-Flash)、[NVIDIA API 參考](https://docs.api.nvidia.com/nim/reference/z-ai-glm-5-3-flash-infer)

### 3. 完整銘牌裁切，再考慮失敗後局部重讀

目前圖片最長邊預設 2560 pixels，JPEG 品質 95。可先測試移除銘牌外的大片背景，保留完整銘牌、所有型號標題及序號區；之後才比較較小解析度。室內機型號、序號可能在邊緣或另一張貼紙，裁切不能把它們排除；細字在縮圖後也可能不再可讀。NVIDIA 明確提醒圖片解析度與品質會影響結果。[NVIDIA 圖片限制說明](https://docs.api.nvidia.com/nim/reference/z-ai-glm-5-3-flash)

如果完整銘牌仍辨識失敗或重要文字不清，才考慮讓使用者選取有問題的區域，進行有次數上限的局部／分塊重讀，保留原圖與每次結果。未標示造成的 null 不應自動觸發重讀。這次只在專案外進行一次人工選區實驗，尚未實作自動裁切或選區 UI；每張都分塊或同時送完整圖與多個局部圖，反而可能增加請求、視覺輸入與時間。

目前未找到此 NIM 模型專屬的圖片 token 計算公式，或可直接使用的低細節、像素／tiles 控制參數。不能將其他模型的 `detail`、`max_pixels` 或 tiles 設定直接套入並宣稱有效。

## 不把哪些設定當成速度保證

- `max_tokens` 是硬性生成上限；官方說明到上限就停止，過小可能截斷 JSON。先保持 4096，若日後調整需檢查 `finish_reason` 與完整輸出，不把降低上限當成按比例加速。[API 定義](https://docs.api.nvidia.com/nim/reference/z-ai-glm-5-3-flash-infer)
- 串流可以提早顯示部分回覆，但本系統要收到完整 JSON 才能校正；沒有證據顯示改成串流就能縮短完整結果時間。
- NVIDIA 端點已使用 FP8 與 MTP speculative decoding；自架服務的 GPU、量化或引擎參數不是此託管 API 的客戶端開關。[NVIDIA 端點部署資訊](https://docs.api.nvidia.com/nim/reference/z-ai-glm-5-3-flash)
- 增加 Worker 或同時送出多次請求不等於單張更快，還可能帶來排隊、限流與額外用量。後續優化仍先在 Mac 驗證，接受後再按 [NAS 發布流程](nas-deployment.md) 更新。
