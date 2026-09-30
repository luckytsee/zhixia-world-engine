/**
 * 接线入口（宿主只需要改这一个文件）。
 *
 * 用法：在你的 App 启动时调 WeProactiveBootstrap.setup(...)，之后 WorkScheduler
 * 唤醒时本包自己去取。示例实现见本文件底部的 Sample* 三个类——
 * 把它们换成你自己的同步层 / 聊天库 / LLM 客户端即可。
 */

import { SnapshotSource, ChatSink, LlmClient, WeSnapshotDto, WeChatMsgDto } from './WePorts';
import { WeProactiveDeps } from '../proactive/WeProactiveCycle';

export class WeProactiveBootstrap {
  private static _deps: WeProactiveDeps | null = null;
  private static _snap: SampleSnapshotSource | null = null;
  private static _sink: SampleChatSink | null = null;
  private static _llm: SampleOpenAiCompatClient | null = null;

  /** 宿主在 App 启动时调一次（重复调会覆盖，便于热替换） */
  static setup(snapshotSource: SnapshotSource, chatSink: ChatSink, llm: LlmClient): void {
    WeProactiveBootstrap._deps = new WeProactiveDeps(snapshotSource, chatSink, llm);
  }

  /** 本包内部取依赖；没接线 → 抛错（唤醒时日志可见，好排查） */
  static deps(): WeProactiveDeps {
    if (WeProactiveBootstrap._deps === null) {
      throw new Error('WeProactiveBootstrap.setup(...) has not been called');
    }
    return WeProactiveBootstrap._deps;
  }

  // ---- 示例默认实例（宿主替换成自己的实现即可） ----

  static sampleSnapshotSource(): SnapshotSource {
    if (WeProactiveBootstrap._snap === null) {
      WeProactiveBootstrap._snap = new SampleSnapshotSource();
    }
    return WeProactiveBootstrap._snap;
  }

  static sampleChatSink(): ChatSink {
    if (WeProactiveBootstrap._sink === null) {
      WeProactiveBootstrap._sink = new SampleChatSink();
    }
    return WeProactiveBootstrap._sink;
  }

  static sampleLlmClient(): LlmClient {
    if (WeProactiveBootstrap._llm === null) {
      // ⚠️ baseUrl / apiKey 由宿主注入，别写死在代码里
      WeProactiveBootstrap._llm = new SampleOpenAiCompatClient('', '', '');
    }
    return WeProactiveBootstrap._llm;
  }
}

// ---------------- 以下是可直接替换的示例实现 ----------------

/** 示例：从内存里拿一份快照（换成你的文件/网络同步层） */
export class SampleSnapshotSource implements SnapshotSource {
  private data: WeSnapshotDto | null = null;

  set(data: WeSnapshotDto | null): void {
    this.data = data;
  }

  load(): WeSnapshotDto | null {
    return this.data;
  }
}

/** 示例：把消息写进数组（换成你的本地库 + 推送队列） */
export class SampleChatSink implements ChatSink {
  readonly messages: WeChatMsgDto[] = [];

  async insert(msg: WeChatMsgDto): Promise<void> {
    this.messages.push(msg);
  }
}

/**
 * 示例：LLM 客户端（OpenAI 兼容 /chat/completions）。
 * ⚠️ key 与地址由宿主注入，**不要写进代码**——环境变量/安全存储/服务端代理都行。
 */
export class SampleOpenAiCompatClient implements LlmClient {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly model: string;

  constructor(baseUrl: string, apiKey: string, model: string) {
    this.baseUrl = baseUrl;
    this.apiKey = apiKey;
    this.model = model;
  }

  async chatComplete(messages: object[]): Promise<string | null> {
    // 用 @kit.NetworkKit 的 http 发一次 POST；失败返回 null（调用方会降级成纯世界状态文案）。
    // 示例刻意留空，避免本仓库携带任何网络/凭据细节。
    return null;
  }
}
