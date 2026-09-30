/**
 * 演示页：显示移植自检结果 + 手动跑一次主动开口。
 *
 * 真实的 App 里这一页不存在——它只是让这个仓库**开箱能跑、能看见证据**：
 *   ① 自检：Python 引擎的验收向量，逐字段对答案（4/4 才算移植成功）
 *   ② 手动触发：跑一轮真实的主动开口链路（世界补算 → LLM → 通知 → 落库）
 */

import { hilog } from '@kit.PerformanceAnalysisKit';
import { common } from '@kit.AbilityKit';
import { WeWorldVectors } from '../world/WeWorldVectors';
import { WeProactiveCycle, WeProactiveRunOpts } from '../proactive/WeProactiveCycle';
import { WeProactiveBootstrap } from '../ports/WeProactiveBootstrap';

@Entry
@Component
struct Index {
  @State vectors: string = '（未运行）';
  @State lastRun: string = '（未触发）';
  @State busy: boolean = false;

  build() {
    Column({ space: 16 }) {
      Text('World Engine · Phone Port').fontSize(20).fontWeight(FontWeight.Bold)
      Text('① 移植自检（Python 引擎验收向量）').fontSize(14)
      Text(this.vectors).fontSize(18).fontColor('#0A6')
      Button('跑一次自检').onClick(() => {
        this.vectors = WeWorldVectors.run();
      })
      Divider()
      Text('② 主动开口（世界补算 → LLM → 通知 → 落库）').fontSize(14)
      Text(this.lastRun).fontSize(14)
      Button(this.busy ? '跑着呢…' : '现在开口一次').enabled(!this.busy)
        .onClick(() => {
          this.runOnce();
        })
    }
    .width('100%').height('100%').justifyContent(FlexAlign.Center).padding(24)
  }

  private runOnce(): void {
    this.busy = true;
    const ctx = getContext(this) as common.UIAbilityContext;
    const opts = new WeProactiveRunOpts();
    opts.source = 'debug';
    opts.debug = true; // 无由头也强行开口，便于验证链路
    WeProactiveCycle.run(ctx, opts, WeProactiveBootstrap.deps())
      .then((msg: string): void => {
        this.lastRun = msg;
      })
      .catch((err: Object): void => {
        this.lastRun = '失败：' + JSON.stringify(err);
        hilog.error(0x0926, 'WorldEngine', 'run failed: %{public}s', JSON.stringify(err));
      })
      .finally(() => {
        this.busy = false;
      });
  }
}
