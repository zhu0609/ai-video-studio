# ComfyUI可选版：接入与验证

本版本已经实现ComfyUI图片服务适配器、工作流管理和前端操作入口。**尚未连接用户的真实ComfyUI服务，也没有安装云GPU、模型权重、LoRA或ControlNet。** 当前的协议测试通过模拟服务器响应完成，不代表真实模型生成质量或人物一致性已经验证。

原有Seedream图片、Seedance视频、MiniMax配音和FFmpeg合成路线继续可用。ComfyUI暂只替换图片生成步骤，视频仍由Seedance生成。

## 现在可以查看什么

1. 在工作台左侧打开“ComfyUI工作区”，查看执行关系、服务配置状态、连接检查入口及工作流管理。
2. 下载两份内置API模板：标准SDXL文生图、SDXL参考图图生图。
3. 新建项目，选择ComfyUI，再选择工作流、随机种子；参考图模板支持上传PNG、JPEG或WEBP图片，最大10MB、2500万像素。
4. 演示模式可以预览项目流程，但仍使用明确标注的程序素材；不会调用ComfyUI或付费模型。真实模式在服务地址未配置时禁止提交。

## 连接真实ComfyUI

项目根目录 `.env` 已添加以下可选项，原有密钥没有被替换：

```dotenv
COMFYUI_BASE_URL=
COMFYUI_API_KEY=
COMFYUI_TIMEOUT_SECONDS=900
COMFYUI_POLL_INTERVAL_SECONDS=2
TEXT_RESPONSE_FORMAT=auto
```

本机原生ComfyUI常见地址为 `http://127.0.0.1:8188`；Docker内访问宿主机时使用可达的主机地址，例如Docker Desktop的 `http://host.docker.internal:8188`，不能把容器内127.0.0.1当成宿主机。云端服务填写其实际原生ComfyUI API地址，服务需要Bearer反向代理鉴权时填写COMFYUI_API_KEY。原生无鉴权服务可留空。

本适配器针对原生 `/prompt`、`/history/{prompt_id}`、`/view`、`/upload/image` 协议，不宣称兼容Comfy Cloud或其他云厂商不同路径、签名及上传协议。

保存配置后重启服务。工作区的“检查连接与所选工作流”只查询 `/system_stats` 和 `/object_info`，不提交生成请求；会报告缺少的节点、checkpoint占位符和未安装的checkpoint名称。

用户电脑已检测到RTX3050笔记本显卡、4GB显存。本次没有执行本地模型推理，不能承诺这块显卡可流畅执行示例SDXL尺寸。是否能运行取决于模型、精度、显存卸载及工作流；生产负载建议在确认实际硬件与工作流耗时后配置。

## 从示例变成可运行工作流

示例中的 `REPLACE_WITH_INSTALLED_CHECKPOINT.safetensors` 必须改为ComfyUI实际安装的checkpoint。占位符模板不能用于真实模式，避免先产生脚本费用才发现模型不存在。

推荐顺序：在ComfyUI里调通 → Export (API)导出 → 导入本项目 → 检查连接和所选工作流 → 先生成单条短视频。普通含`nodes`和`links`的画布格式不能直接提交。

可直接导入原生API节点JSON；程序尝试识别正向CLIPTextEncode、尺寸、seed、LoadImage和唯一SaveImage。复杂工作流应使用下列包装格式显式指定绑定：

```json
{
  "name": "我的分镜工作流",
  "description": "已在ComfyUI里跑通的工作流",
  "workflow": {"这里放完整的API节点图": {}},
  "bindings": {
    "prompt": {"node": "6", "input": "text"},
    "width": {"node": "5", "input": "width"},
    "height": {"node": "5", "input": "height"},
    "seed": {"node": "3", "input": "seed"},
    "reference": {"node": "10", "input": "image"}
  },
  "output_node": "9"
}
```

上面的JSON是结构说明，不能直接运行。需要替换为实际完整节点图和节点ID。没有参考图的工作流应省略reference绑定；有该绑定的工作流必须上传参考图。输出必须为SaveImage。

图片尺寸当前注入为竖屏768×1344、横屏1344×768、方图1024×1024，最终视频仍按项目画幅归一化。种子按项目种子、视频序号、镜头序号及图片修订派生并记录在实际请求中。固定种子有助于复现，不单独保证人物身份一致。

基础参考图模板是img2img，主要参考构图及色彩。需要人物身份控制时，应导入已验证的IP-Adapter、人物LoRA或其他参考人物工作流；本项目不会自动安装其节点和权重。仅支持模型节点工作流，不允许把API密钥字段直接嵌入导入JSON。

## 恢复与存储

- 每个项目保存独立工作流快照、工作流ID、图片服务、参考图路径和种子，不会因重新导入文件改变旧项目。
- 真实项目保存ComfyUI服务地址，地址变化后阻止恢复到另一个服务，避免把旧prompt_id当成新服务的任务。
- ComfyUI的prompt_id保存在图片调用账本；Seedance的task_id独立保留。
- 图片下载失败或等待超时后，恢复时查询已有prompt_id，不自动重新提交工作流。队列历史被清空时可能无法找回结果，需要核查后显式重做。
- 提交响应不确定时不自动重发，可在调用记录中绑定已经核实的prompt_id。
- 参考图规范为PNG后上传ComfyUI，图片输出从配置的服务/view取回；不接受重定向或输出路径越界。
- 本机进程串行控制ComfyUI执行；Celery模式有Redis服务锁，但Docker和多Worker故障注入尚未实测。

## 脚本稳定性改进

新增JSON对象提取，可处理代码围栏、前后说明、尾随文字和常见中英字段别名。严格校验镜头数和必要字段，失败时最多一次有记录的纠错请求。没有通过补空镜头、随意截掉镜头来伪装成功。

`TEXT_RESPONSE_FORMAT=auto`对未知ep接入点保留原协议兼容性；明确支持时可选择json_object或json_schema。结构化格式是否支持取决于实际文本模型。历史失败响应可以先用新解析器重新解析，纠错调用使用独立账本key且可复用。

## 本次验证

- TypeScript检查与前端生产构建通过。
- 39项离线测试通过：ComfyUI提示词/尺寸/种子注入、参考图、ID恢复、下载失败重试、未重提任务、旧库迁移、API工作流管理、图片上传、连接检查和脚本纠错等。
- 使用协议模拟器测试实际pipeline.image_step选择ComfyUI适配器，删除本地输出后恢复下载，生成提交仍只有一次。
- 浏览器验证了工作区导航、图片来源切换、参考图工作流选择、真实文件上传及缩略图展示。
- 升级前数据库已备份在任务work目录，升级后原有6个项目保留。
- 这次没有新增付费模型调用，也没有在本机或云端运行真实ComfyUI模型；没有真实人物一致性、速度或降本效果的验证结论。

官方协议参考：[服务器API](https://github.com/Comfy-Org/docs/blob/main/development/comfyui-server/comms_routes.mdx)、[API工作流导出](https://github.com/Comfy-Org/docs/blob/main/development/api-development/quickstart.mdx)。
