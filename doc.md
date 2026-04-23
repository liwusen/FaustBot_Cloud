# FaustBot Cloud Inference Server

独立的 HTTP 云推理服务，代码、CLI、配置和本地存储都位于 `cloud_inference_server` 目录下。

## 功能

- FastAPI 提供的 HTTP API
- TTS 转发到本地 GPT-SoVITS-Bundle
- ASR 转发到现有 FunASR 服务
- Service Key 鉴权，格式为 `FSK-xxxxxxxxxxxxxxxxxxxxxxx`
- SQLite 计费与额度限制
- 参考音频上传、缓存与 `refer_hash` 复用
- CLI 配置与 Service Key 管理

## 计费规则

- TTS: CJK 汉字每个 `1 Point`，非空白非汉字字符每个 `0.15 Point`
- ASR: 按上传音频总时长向上取整，`1 秒 = 1 Point`
- 默认额度: `5000 Points/Day`，`1500 Points/Hour`

## 初始化配置

```powershell
D:/dev/faustbot/faust/.runtime/python.exe cloud_inference_server/cli.py init-config
D:/dev/faustbot/faust/.runtime/python.exe cloud_inference_server/cli.py show-config
```

修改配置示例：

```powershell
D:/dev/faustbot/faust/.runtime/python.exe cloud_inference_server/cli.py set gpt_sovits_base_url "http://127.0.0.1:5000"
D:/dev/faustbot/faust/.runtime/python.exe cloud_inference_server/cli.py set funasr_base_url "http://127.0.0.1:1000"
D:/dev/faustbot/faust/.runtime/python.exe cloud_inference_server/cli.py set hourly_limit_points 1500
```

## Service Key 管理

```powershell
D:/dev/faustbot/faust/.runtime/python.exe cloud_inference_server/cli.py create-key --name demo --note local-test
D:/dev/faustbot/faust/.runtime/python.exe cloud_inference_server/cli.py list-keys
D:/dev/faustbot/faust/.runtime/python.exe cloud_inference_server/cli.py disable-key FSK-xxxxxxxxxxxxxxxxxxxxxxx
D:/dev/faustbot/faust/.runtime/python.exe cloud_inference_server/cli.py enable-key FSK-xxxxxxxxxxxxxxxxxxxxxxx
D:/dev/faustbot/faust/.runtime/python.exe cloud_inference_server/cli.py reset-usage FSK-xxxxxxxxxxxxxxxxxxxxxxx
```

## 启动服务

```powershell
D:/dev/faustbot/faust/.runtime/python.exe cloud_inference_server/cli.py runserver
```

默认监听地址来自 `cloud.config.json`，缺省为 `http://127.0.0.1:18980`。

## API

### 上传参考音频

```powershell
curl -X POST "http://127.0.0.1:18980/v1/references" ^
  -H "Authorization: Bearer FSK-xxxxxxxxxxxxxxxxxxxxxxx" ^
  -F "file=@demo.wav" ^
  -F "prompt_text=一二三。" ^
  -F "prompt_language=zh"
```

### TTS

```powershell
curl -X POST "http://127.0.0.1:18980/v1/tts" ^
  -H "Authorization: Bearer FSK-xxxxxxxxxxxxxxxxxxxxxxx" ^
  -H "Content-Type: application/json" ^
  -d "{\"refer_hash\":\"<refer_hash>\",\"text\":\"你好，世界\",\"text_language\":\"zh\"}" ^
  --output out.wav
```

### ASR

```powershell
curl -X POST "http://127.0.0.1:18980/v1/asr" ^
  -H "Authorization: Bearer FSK-xxxxxxxxxxxxxxxxxxxxxxx" ^
  -F "file=@chunk.wav"
```

## FaustBot 客户端接入

在 FaustBot 配置器中：

- `TTS_MODE` 设为 `faustbot-cloud`
- `ASR_MODE` 设为 `faustbot-cloud`
- `FAUSTBOT_CLOUD_BASE_URL` 填云服务地址
- `FAUSTBOT_CLOUD_SERVICE_KEY` 填 CLI 创建出的 Service Key
- `FAUSTBOT_CLOUD_DEFAULT_REFER_HASH` 填上传参考音频后得到的哈希

客户端 backend 会继续走原有 `/faust/audio/tts` 和 `/faust/audio/asr`，但内部转发到 FaustBot Cloud。