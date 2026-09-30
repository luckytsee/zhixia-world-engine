/**
 * 最小依赖桩（示例）——开源包不携带宿主 App 的实现。
 *
 * 本文件把「世界引擎移植 + 主动发起」真正需要的**四个外部能力**降到最小，
 * 让整包能独立读懂、独立编译。接进你自己的 App 时，把这里的实现换成你的：
 *   1. SnapshotStore —— 从你的同步层拿一份快照（含 world / gifts 段）
 *   2. ChatSink      —— 把"她主动说的那句话"写进你的聊天记录 + 通知
 *   3. LlmClient     —— 一次 chat/completions 调用
 *   4. 快照/消息的数据形状 —— 见 WeSnapshotDto / WeChatMsgDto
 *
 * ⚠️ 本文件**不含任何凭据**：API key / 内网地址由调用方注入。
 */

import { common } from '@kit.AbilityKit';

// ---------- 1) 快照（数据形状照抄上游同步协议，字段保持蛇形，别改名） ----------

/** 世界段：{engine_version, state, rules, saved_at}。state/rules 的内部形状见 world/WeWorldRules.ets */
export interface WeWorldSegmentDto {
  engine_version?: number;
  state?: object;
  rules?: object;
  saved_at?: number;
}

/** 礼物段：手机端只读 unopened_packages 注入一行，不落账不回传 */
export interface WeGiftsSegmentDto {
  items?: object[];
  unopened_packages?: number;
  wishes_waiting?: number;
}

/** 同步下来的快照（这里只列本包用得到的字段） */
export interface WeSnapshotDto {
  persona?: string;
  facts?: object[];
  episodes?: object[];
  /** 世界段；缺失/null = 不动缓存（语义同上游：null ≠ 明确没有） */
  world?: WeWorldSegmentDto | null;
  worldPresent?: boolean;
  gifts?: WeGiftsSegmentDto | null;
  giftsPresent?: boolean;
}

/** 快照读取端口：换成你自己的持久化/网络层 */
export interface SnapshotSource {
  load(): WeSnapshotDto | null;
}

// ---------- 2) 聊天落库（她主动说的那句话） ----------

/** 聊天消息（与上游同形状；图片/表情字段本包不用） */
export interface WeChatMsgDto {
  id: string;
  /** 'user' | 'assistant' */
  role: string;
  content: string;
  ts: number;
  /** 0=待推送 1=已入库 2=被拒收 */
  synced: number;
  /** YYYY-MM-DD */
  day: string;
  /** 图片消息的本地路径（'' = 纯文本） */
  img: string;
  /** 表情图资源名（'' = 无） */
  sticker: string;
}

/** 聊天写入端口：把你的本地库实现放这里 */
export interface ChatSink {
  insert(msg: WeChatMsgDto): Promise<void>;
}

// ---------- 3) LLM 客户端 ----------

/** 一次对话补全；失败/空 → null（调用方会降级成纯世界状态文案） */
export interface LlmClient {
  chatComplete(messages: object[]): Promise<string | null>;
}

// ---------- 4) 日志 ----------

/** 本包统一日志前缀，方便 `hdc shell hilog | grep` 过滤 */
export const ZX_LOG_DOMAIN: number = 0x0926;
export const ZX_LOG_TAG: string = 'WorldEngine';

/** 通知/横幅标题（换成你的 App 名） */
export const APP_NAME: string = 'Assistant';

/** 延迟初始化用的上下文类型别名（宿主传什么就是什么） */
export type HostContext = common.Context;
