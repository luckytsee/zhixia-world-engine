/**
 * 通道 B：WorkScheduler 唤醒式主动（任务书 §8.1）。
 *
 * 系统不定期唤醒（时机系统说了算，会推迟/合并/压制）→ 唤醒时跑一轮
 * WeProactiveCycle：世界补算到当下 → 锚点窗/由头判断 → 节流 → 有由头才调
 * DeepSeek → 本地通知 → 原话落库推回 PC。
 *
 * ⚠️ §8.4 观测：每次唤醒记录"距上次唤醒的间隔"（hilog tag WeProactive），
 * 连跑 24–48h 的间隔分布 = 延迟分布。锚点（早安/晚安）现在也靠唤醒在
 * 时间窗内补说（原 reminderAgentManager 预约被 1700002 管控配额卡死），
 * 所以这张表决定的不只是"事件驱动/配额驱动"，还决定锚点的准点程度。
 */

import { WorkSchedulerExtensionAbility, workScheduler } from '@kit.BackgroundTasksKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { WeProactivity } from './WeProactivity';
import { WeProactiveCycle, WeProactiveRunOpts } from './WeProactiveCycle';
import { WeProactiveBootstrap } from '../ports/WeProactiveBootstrap';

const ZX_LOG_DOMAIN: number = 0x0926;
const ZX_LOG_TAG: string = 'WeProactive';

export default class WeWorkSchedulerAbility extends WorkSchedulerExtensionAbility {
  /** B 唤醒周期的注册参数（30min，任务书 §8.4；系统实际多久醒一次看日志） */
  static readonly WORK_ID: number = 100;
  static readonly REPEAT_MS: number = 30 * 60 * 1000;

  onWorkStart(work: workScheduler.WorkInfo): void {
    hilog.info(ZX_LOG_DOMAIN, ZX_LOG_TAG, 'B 唤醒: workId=%{public}d', work.workId);
    this.runCycle().catch((err: Object) => {
      hilog.error(ZX_LOG_DOMAIN, ZX_LOG_TAG, 'B 周期异常: %{public}s', JSON.stringify(err));
    });
  }

  onWorkStop(work: workScheduler.WorkInfo): void {
    hilog.info(ZX_LOG_DOMAIN, ZX_LOG_TAG, 'B 周期结束: workId=%{public}d', work.workId);
  }

  private async runCycle(): Promise<void> {
    const ctx = this.context;
    const nowMs: number = Date.now();
    // §8.4 延迟观测：两次唤醒的间隔 = 实际周期（只有真唤醒记账，调试入口不算）
    const pro = new WeProactivity();
    pro.init(ctx);
    const prevWake: number = pro.markWake(nowMs);
    if (prevWake > 0) {
      hilog.info(ZX_LOG_DOMAIN, ZX_LOG_TAG, '唤醒间隔=%{public}d分钟（实际周期，§8.4 观测）',
        Math.round((nowMs - prevWake) / 60000));
    }
    const opts = new WeProactiveRunOpts();
    opts.source = 'B';
    opts.debug = false;
    await WeProactiveCycle.run(ctx, opts, WeProactiveBootstrap.deps());
  }
}
