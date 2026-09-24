# report.json 接口

读取本次 messages.json，使用其 messages[].id 原样作为引用（不要用序号替代ID）。结构如下；值为说明，需替换成实际有来源的内容。

```json
{
  "schema_version": 1,
  "overview": {"text": "简短概览", "refs": ["实际消息ID"]},
  "topics": [{"title": "话题", "text": "讨论及结论", "refs": ["实际消息ID"]}],
  "todos": [{"item": "明确提出的事项", "owner": "未明确", "deadline": "未明确", "status": "未明确", "refs": ["实际消息ID"]}],
  "confirmed": [{"text": "已确认事项（区别个人自述与核实事实）", "refs": ["实际消息ID"]}],
  "unresolved": [{"text": "未解决问题", "refs": ["实际消息ID"]}],
  "other": [{"text": "其他必要信息", "refs": ["实际消息ID"]}],
  "coverage": {"reviewed_message_ids": ["实际读过的全部ID，每个恰好一次"], "method": "Codex session"}
}
```

没有对应内容的列表设为[]，所有列表字段保留。正常非空数据的每一项/概览都需要refs，且必须指向本次消息。空数据只允许说明未读到本地消息的overview（refs=[]）以及空列表；不能推断群里没有发言。

messages.json 元数据包含 group_name/group_id/account_id/start/end/timezone/message_count/speaker_count/scope/warnings/shards/snapshot_at。不要为了通过校验修改采集数据；统计冲突时先找原因。

媒体type标记不是可见内容。card为实际可读字段，quote可带原引用内容，但引用的server_id可能不在本次时间窗，不能伪造一条消息纳入统计。结论引用承载该quote的本次消息ID，并明确引用关系。
