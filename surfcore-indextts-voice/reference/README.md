# 参考音频放这里

IndexTTS 是**零样本克隆**：它不认识"某个人"，只听你给的一小段音频去模仿。

## 要求

| 项 | 建议 |
| --- | --- |
| 长度 | 3~10 秒（19 秒也能用，但音色稳定性并不更好，反而更慢） |
| 内容 | 单人、干净、无背景音乐、无混响、无他人插话 |
| 格式 | wav（16/24/48 kHz 都行）或 mp3 |
| 情绪 | 用你希望她平时说话的那种语气录 |

## 怎么用

安装时指定：

```powershell
.\scripts\install.ps1 -RefAudio ".\reference\我的声音.wav" -Character xiaoyu
```

脚本会把它复制成 `<voice-packs>\api\ckyp\xiaoyu.wav`。

想换音色：

1. 换掉 `api\ckyp\xiaoyu.wav`；
2. 或者加一段映射到 `index-tts-bridge\config.json`：

   ```jsonc
   "voices": {
     "xiaoyu":  { "ref_audio": "xiaoyu.wav" },
     "another": { "ref_audio": "another.wav" }
   }
   ```

3. 在 SurfCore 设置里把 `tts.character` 改成对应名字，
   并在 `pack\config.toml` 的 `[voice.characters]` 里加上同名键（否则设置页会提示角色不存在）。
4. 改完把 `tts.cacheVersion` +1，否则旧的合成缓存还会命中。

> 本仓库不附带任何真人音频。放在这里的文件不会进 git（见 `.gitignore`）。
