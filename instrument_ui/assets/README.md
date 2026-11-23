# UI 素材

`boot-background.png`：依專案 `UI/UI 的圖片/01.jpg`，透過 **內建 imagegen 工具，編輯模式**整理重建的開機背景。不是原始設計檔或逐像素還原；原參考圖未覆寫。已複製進專案，執行時直接讀取本機 PNG，不呼叫生成服務。

`pimex-logo.png`：直接複製自 `UI/visily-static-cv-96well-selection-interface1-html/assets/IMG_1.png` 的原始透明 Logo。

生成提示詞規格（整理記錄）：

> Use the supplied 01.jpg as the edit target. Reconstruct a clean 4:3 background artwork for an 800×600 scientific instrument touchscreen. Preserve the reference composition: a cyan illuminated multiwell device on the left, a tilted instrument display with a cyan waveform on the right, cables, floating reflective bubbles, and a dark navy/purple laboratory background with cyan digital light trails. Remove the laptop bezel, surrounding browser/page area, browser fullscreen notification, title, buttons, attribution, and watermark. Rebuild the obscured background naturally. Keep the scientific equipment, perspective, cyan lighting, and navy/purple palette close to the reference. Output only the full-bleed background artwork, with no UI, no lettering, no logos, and no text.

標題、兩個模式按鈕、工具入口及署名由 PyQt 繪製，保持文字清晰且可操作。背景僅作裝飾，不用圖中的孔數或波形表示真實量測狀態。
