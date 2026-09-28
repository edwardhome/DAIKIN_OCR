# 辨識速度改善

更新日期：2026-09-28。本機候選版已將新辨識縮為室外機型號、室內機型號、序號三欄，使用 `nameplate_identity_v002`。歷史 19 欄結果、人工版本與原 `nameplate_v001` 保留。NAS 目前為 `20260928-branding-v2` 名稱修補版，仍使用舊辨識流程；三欄版須待使用者本機驗收接受後才部署。

## 已做的改變與單次實測

優先減少要讀取及生成的欄位，維持每次 Attempt 選定一個模型。目前預設為 NVIDIA NIM `z-ai/glm-5.3-flash`，`MODEL_MAX_TOKENS=4096` 保留，沒有同時換模型、增加並行或套用圖片裁切。

本機同一張合成測試卡的兩次紀錄：

| 本機版本 | 模型呼叫 | 輸入 tokens | 輸出 tokens | 總 tokens |
| --- | ---: | ---: | ---: | ---: |
| 原 19 欄 | 77.67 秒 | 2,575 | 983 | 3,558 |
| 新 3 欄 | 34.11 秒 | 1,891 | 182 | 2,073 |

新三欄這次包含前處理的時間為 34.14 秒，三欄皆與合成卡答案相符。兩個版本各只有一次呼叫，顯示此次縮減後的方向，**不是平均延遲、固定加速比例或現場準確率**；託管端點負載與網路條件也可能影響結果。詳細驗證見 [驗證紀錄](verification.md)。

## 後續實驗順序

### 1. 先驗收三欄流程

使用固定照片確認兩個型號不對調、序號字符完整、未印的欄位保持 null；同時核對人工修改、分享、歷史 19 欄與資料匯出。每輪保留同圖、模型、Prompt、圖片尺寸與 token／耗時紀錄，只改一個條件。速度與三欄 exact match 要一起看，不能只選最快的一次。新舊評分依 [共同欄位規則](benchmark.md) 比較。

### 2. 再試較低思考量，尚未套用

NVIDIA 的 GLM-5.3-Flash 模型文件明確列出 `reasoning_effort` 可用 `low`、`high`、`max`，省略時為 `max`。下一個可做的本機對照實驗是 `reasoning_effort: "low"`。[NVIDIA 模型文件](https://docs.api.nvidia.com/nim/reference/z-ai-glm-5-3-flash)

原廠說明這個模型的思考不能關閉；不可假定 `enable_thinking: false` 有效。`clear_thinking` 控制歷史思考是否保留，也不是關閉本次思考。[Z.ai 模型說明](https://docs.z.ai/guides/vlm/glm-5.3-flash)、[原廠 chat template](https://huggingface.co/zai-org/GLM-5.3-Flash/raw/main/chat_template.jinja)

vLLM 配方支援頂層 `reasoning_effort` 或 `chat_template_kwargs.reasoning_effort`。NVIDIA 模型介紹有此參數，但該端點的請求參數表未列出；套用前仍須確認託管端點接受參數、正常完成 JSON，以及難字／序號正確率。[vLLM 官方配方](https://recipes.vllm.ai/zai-org/GLM-5.3-Flash)、[NVIDIA API 參考](https://docs.api.nvidia.com/nim/reference/z-ai-glm-5-3-flash-infer)

### 3. 完整銘牌裁切，再考慮失敗後局部重讀

目前圖片最長邊預設 2560 pixels，JPEG 品質 95。可先測試移除銘牌外的大片背景，保留完整銘牌、所有型號標題及序號區；之後才比較較小解析度。室內機型號、序號可能在邊緣或另一張貼紙，裁切不能把它們排除；細字在縮圖後也可能不再可讀。NVIDIA 明確提醒圖片解析度與品質會影響結果。[NVIDIA 圖片限制說明](https://docs.api.nvidia.com/nim/reference/z-ai-glm-5-3-flash)

如果完整銘牌仍辨識失敗或重要文字不清，才考慮讓使用者選取有問題的區域，進行有次數上限的局部／分塊重讀，保留原圖與每次結果。未標示造成的 null 不應自動觸發重讀。這是未實作的方案；每張都分塊或同時送完整圖與多個局部圖，反而可能增加請求、視覺輸入與時間。

目前未找到此 NIM 模型專屬的圖片 token 計算公式，或可直接使用的低細節、像素／tiles 控制參數。不能將其他模型的 `detail`、`max_pixels` 或 tiles 設定直接套入並宣稱有效。

## 不把哪些設定當成速度保證

- `max_tokens` 是硬性生成上限；官方說明到上限就停止，過小可能截斷 JSON。先保持 4096，若日後調整需檢查 `finish_reason` 與完整輸出，不把降低上限當成按比例加速。[API 定義](https://docs.api.nvidia.com/nim/reference/z-ai-glm-5-3-flash-infer)
- 串流可以提早顯示部分回覆，但本系統要收到完整 JSON 才能校正；沒有證據顯示改成串流就能縮短完整結果時間。
- NVIDIA 端點已使用 FP8 與 MTP speculative decoding；自架服務的 GPU、量化或引擎參數不是此託管 API 的客戶端開關。[NVIDIA 端點部署資訊](https://docs.api.nvidia.com/nim/reference/z-ai-glm-5-3-flash)
- 增加 Worker 或同時送出多次請求不等於單張更快，還可能帶來排隊、限流與額外用量。後續優化仍先在 Mac 驗證，接受後再按 [NAS 發布流程](nas-deployment.md) 更新。
