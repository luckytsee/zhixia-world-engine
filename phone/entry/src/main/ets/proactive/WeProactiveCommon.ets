/**
 * 主动发起的公共件（任务书 §8）：通知发布 + 她的原话落库。
 * 通道 A（预约式）与通道 B（唤醒式）共用，落库纪律同 §8.6：
 * 原话落 msgList 当她发的消息（synced=0），等同步推回 PC 进记忆管道。
 */

import { notificationManager } from '@kit.NotificationKit';
import { common, wantAgent } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { WeTextKit } from '../ports/WeTextKit';
import { APP_NAME } from '../ports/WePorts';
import type { ChatSink, WeChatMsgDto } from '../ports/WePorts';
import type { WeWorldState } from '../world/WeWorldRules';

const WE_LOG_DOMAIN: number = 0x0926;
const WE_LOG_TAG: string = 'WeProactive';

export class WeProactiveCommon {
  /** bundle 名（wantAgent 用；与 AppScope/app.json5 一致） */
  private static readonly BUNDLE: string = 'com.example.yourapp';

  /** 本地横幅：标题 = APP_NAME，正文是主动生成的那句话；点开回到聊天界面 */
  static async publishMsg(ctx: common.Context, text: string): Promise<void> {
    try {
      const agent = await wantAgent.getWantAgent({
        wants: [{ bundleName: WeProactiveCommon.BUNDLE, abilityName: 'EntryAbility' }],
        operationType: wantAgent.OperationType.START_ABILITY,
        requestCode: 0
      });
      const request: notificationManager.NotificationRequest = {
        id: 2, // 与 Index 聊天回复横幅(id 1)区分，但同为新顶旧不堆叠
        notificationSlotType: notificationManager.SlotType.SOCIAL_COMMUNICATION,
        wantAgent: agent,
        content: {
          notificationContentType: notificationManager.ContentType.NOTIFICATION_CONTENT_BASIC_TEXT,
          normal: {
            title: APP_NAME,
            text: text.replace(/\n/g, ' ')
          }
        }
      };
      await notificationManager.publish(request);
    } catch (err) {
      // 没授权/系统限制：任务书 §8.4 要求"能否发本地通知"的答案就记在这里
      hilog.warn(WE_LOG_DOMAIN, WE_LOG_TAG, '通知发布失败: %{public}s', JSON.stringify(err));
    }
  }

  /** 她主动说的话落本地库（synced=0 → 下次同步推回 PC）；id 带 pro 前缀便于辨认 */
  static async insertAssistantMsg(sink: ChatSink, rawText: string, nowMs: number): Promise<void> {
    const msg: WeChatMsgDto = {
      id: 'pro' + nowMs.toString(),
      role: 'assistant',
      content: rawText,
      ts: nowMs,
      synced: 0,
      day: WeTextKit.ymd(nowMs),
      img: '',
      sticker: ''
    };
    await sink.insert(msg);
  }

  /**
   * LLM 失败时的降级文案（任务书 §8.6：发一句纯世界状态，不发空白通知）。
   * 这是唯一一处固定措辞——只报状态，不替她写情绪。
   */
  static worldShortLine(state: WeWorldState | null): string {
    if (state === null) {
      return '我们这边一切照旧。';
    }
    if (state.fog) {
      return '我们这边起雾了。';
    }
    if (state.rain) {
      return '我们这边在下雨。';
    }
    if (state.moon_tonight) {
      return '今夜有月。';
    }
    if (state.static_day) {
      return '今天我们这边是静日。';
    }
    if (state.wind_reverse) {
      return '我们这边风向反了。';
    }
    return '我们这边是' + state.phase + '。';
  }
}
