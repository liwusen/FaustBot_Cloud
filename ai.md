# 在Backend下编写这个项目的云端API系统

## 要求

1. 使用Python+FastAPI技术栈

2. 支持 TTS和ASR API的云端推理
   
   使用现在的TTS和ASR实现，TTS只需要的实现只需要做到把请求转发到GPT-SoVITS-Bundle中即可
   
3. TTS可以由用户自己设定参考音频
   
   设定方式为:用户调用API上传参考音频，随后获取Hash值作为调用时的附件
   服务端转发时使用这个API
   手动指定当次推理所使用的参考音频:
   
   GET:
   
       `http://127.0.0.1:9880?refer_wav_path=123.wav&prompt_text=一二三。&prompt_language=zh&text=先帝创业未半而中道崩殂，今天下三分，益州疲弊，此诚危急存亡之秋也。&text_language=zh`
   
   POST:
   
   ```json
   {
   
       "refer_wav_path": "123.wav",
   
       "prompt_text": "一二三。",
   
       "prompt_language": "zh",
   
       "text": "先帝创业未半而中道崩殂，今天下三分，益州疲弊，此诚危急存亡之秋也。",
   
       "text_language": "zh"
   
   }
   ```

3. 无需实现GUI前端，为我提供一个CLI进行配置即可






